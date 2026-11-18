"""Channels service (port 8300): APDT/AHDT Layer 2 low-bandwidth channels (design 05, 5.3).

- Africa's Talking callbacks: USSD, incoming SMS, SMS delivery reports, voice
- the USSD menu and the voice IVR from `channels/ussd_menu.yaml`
- the store-and-forward SMS outbox; critical-result pages and sends for other services
- the phone simulator page (`/simulator`)

Phone numbers are direct identifiers. They are used only to answer the caller and are
never logged or forwarded above Layer 2. With `ATRA_AT_USERNAME` and `ATRA_AT_API_KEY`
set, SMS goes through Africa's Talking; otherwise through the simulated network.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Awaitable, Callable, Mapping
from pathlib import Path
from typing import Annotated, Any

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, Response
from pydantic import BaseModel

from apdt.intake.questionnaires import load as load_questionnaire
from apdt.records.episodes import PATIENT_SYSTEM
from atra.backends import Backends
from atra.config import Settings, get_settings
from atra.consent import to_fhir, tools_for_categories
from atra.ids import uuid7
from atra.security import InvalidToken, bearer
from atra.service import Problem, create_app, verifier_of
from atra.telemetry import tracer
from channels.africastalking import AfricasTalkingSms, VoiceResponse, ussd_reply
from channels.apdt_client import ApdtClient, ApdtError
from channels.directory import Contact, Directory, demo_directory
from channels.menu import Menu, Step, default_menu
from channels.outbox import Outbox, SimulatedSms, SmsSender
from channels.speech import PromptCache, Synthesiser

SIMULATOR = Path(__file__).parent / "simulator.html"
SOURCE = "urn:atra:channels"
type PlanSource = Callable[[Contact], Awaitable[list[str]]]


class SendRequest(BaseModel):
    to: str
    text: str
    language: str = "en"
    purpose: str = "care"


class PageRequest(BaseModel):
    alert_id: str
    severity: str
    to: dict[str, str]
    reason: str
    tenant_id: str | None = None


async def _nothing(contact: Contact) -> list[str]:
    return []


def check_in_response(menu: Menu, hdt_id: str, answers: Mapping[str, str]) -> dict[str, Any]:
    """A QuestionnaireResponse of the USSD or voice check-in answers."""
    q = load_questionnaire(menu.menus["check_in"]["questionnaire"])

    def walk(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for item in items:
            if item.get("item"):
                children = walk(item["item"])
                if children:
                    out.append({"linkId": item["linkId"], "text": item.get("text"),
                                "item": children})
                continue
            value = answers.get(item["linkId"])
            if value is None:
                continue
            if item["type"] == "boolean":
                answer: dict[str, Any] = {"valueBoolean": value == "yes"}
            else:
                coding = next(o["valueCoding"] for o in item["answerOption"]
                              if o["valueCoding"]["code"] == value)
                answer = {"valueCoding": coding}
            out.append({"linkId": item["linkId"], "text": item.get("text"), "answer": [answer]})
        return out

    return {"resourceType": "QuestionnaireResponse", "id": f"qr-{uuid7()}",
            "questionnaire": q["url"], "status": "completed",
            "subject": {"identifier": {"system": PATIENT_SYSTEM, "value": hdt_id}},
            "item": walk(q["item"])}


def build_app(settings: Settings | None = None, *, backends: Backends | None = None,
              sms: SmsSender | None = None, apdt: ApdtClient | None = None,
              directory: Directory | None = None, menu: Menu | None = None,
              voices: Mapping[str, Synthesiser] | None = None,
              plans: PlanSource = _nothing, reminders: PlanSource = _nothing) -> FastAPI:
    settings = settings or get_settings()
    app = create_app("channels", settings, backends=backends, title="Channels",
                     description="SMS, USSD and voice channels")
    ready: Backends = app.state.backends
    menu = menu or default_menu()
    directory = directory or demo_directory(secrets.token_bytes(32))
    simulated = SimulatedSms()
    if sms is None:
        user, key = os.environ.get("ATRA_AT_USERNAME"), os.environ.get("ATRA_AT_API_KEY")
        sms = AfricasTalkingSms(user, key) if user and key else simulated
    if apdt is None:
        apdt = ApdtClient(settings.services.apdt,
                          lambda: ready.issuer.issue_service("channels-svc"))
    outbox = Outbox(sms, app.state.audit, ready.events, ref=directory.ref)
    prompts = PromptCache(voices or {})
    app.state.menu, app.state.directory, app.state.outbox = menu, directory, outbox
    app.state.simulated_sms, app.state.prompts, app.state.apdt_client = simulated, prompts, apdt
    spans = tracer("channels")
    audit = app.state.audit

    async def service_client(request: Request) -> str:
        try:
            claims = (await verifier_of(app)).verify(bearer(request.headers.get("authorization")))
        except InvalidToken as exc:
            raise Problem(401, "unauthenticated", str(exc)) from exc
        if not claims.is_service:
            raise Problem(403, "forbidden", "this route takes service clients only")
        return claims.sub

    async def consent_action(step: Step, contact: Contact, phone: str) -> str:
        assert contact.hdt_id is not None
        with spans.start_as_current_span("communication.consent_decision") as span:
            span.set_attribute("atra.channel", "ussd")
            span.set_attribute("atra.withheld", ",".join(step.data["withheld_categories"]))
            consent = to_fhir(contact.hdt_id, step.data["purposes"],
                              tools_for_categories(step.data["withheld_categories"]),
                              consent_id=f"consent-{uuid7()}")
            await apdt.put_consent(contact.tenant_id, contact.hdt_id, consent)
        with spans.start_as_current_span("communication.confirmation_sms"):
            await outbox.enqueue(phone, menu.t("consent.sms", step.language),
                                 language=step.language, purpose="care",
                                 tenant_id=contact.tenant_id, hdt_id=contact.hdt_id)
        return menu.t("consent.saved", step.language)

    async def check_in_action(step: Step, contact: Contact, phone: str) -> str:
        assert contact.hdt_id is not None
        qr = check_in_response(menu, contact.hdt_id, step.data["answers"])
        await apdt.file_bundle(contact.tenant_id, {
            "resourceType": "Bundle", "type": "collection",
            "identifier": {"system": SOURCE, "value": qr["id"]}, "entry": [{"resource": qr}]})
        return menu.t("check_in.done", step.language)

    async def ask_action(step: Step, contact: Contact, phone: str) -> str:
        assert contact.hdt_id is not None
        reply = await apdt.post_message(contact.tenant_id, contact.hdt_id, step.data["text"],
                                        language=step.language, channel="ussd")
        await outbox.enqueue(phone, str(reply.get("reply", "")), language=step.language,
                             purpose="care", tenant_id=contact.tenant_id,
                             hdt_id=contact.hdt_id)
        return menu.t("ask.sent", step.language)

    actions: dict[str, Callable[[Step, Contact, str], Awaitable[str]]] = {
        "consent": consent_action, "check_in": check_in_action, "ask": ask_action,
        "care_plan": await_list(plans, "care_plan.none", menu),
        "reminders": await_list(reminders, "reminders.none", menu)}

    async def run_action(step: Step, contact: Contact, phone: str) -> str:
        try:
            return await actions[str(step.action)](step, contact, phone)
        except ApdtError as exc:
            audit.append(actor={"id": contact.ref, "role": "patient"}, action=str(step.action),
                         target="apdt", purpose="care", outcome="error", reason=str(exc),
                         tenant_id=contact.tenant_id, hdt_id=contact.hdt_id)
            return menu.t("failed", step.language)

    async def walk(channel: str, session_id: str, contact: Contact, phone: str,
                   inputs: list[str], language: str) -> tuple[str, bool]:
        step = menu.walk(inputs, language)
        if step.language != contact.language:
            directory.set_language(phone, step.language)
        if step.node == "consent" and not step.end and len(inputs) == 1:
            # The intro screen explains the data uses before the first choice.
            with spans.start_as_current_span("communication.data_uses"):
                pass
        text, end = step.text, step.end
        if step.action:
            text, end = await run_action(step, contact, phone), True
        audit.append(actor={"id": contact.ref, "role": "patient"}, action=f"{channel}.request",
                     target=session_id, purpose="care", outcome="ok",
                     tenant_id=contact.tenant_id, hdt_id=contact.hdt_id)
        return text, end

    @app.post("/v1/ussd", response_class=PlainTextResponse, tags=["ussd"])
    async def ussd(sessionId: Annotated[str, Form()], serviceCode: Annotated[str, Form()],
                   phoneNumber: Annotated[str, Form()], text: Annotated[str, Form()] = "",
                   networkCode: Annotated[str, Form()] = "") -> str:
        await outbox.flush()
        contact = directory.by_phone(phoneNumber)
        if contact is None or contact.hdt_id is None:
            return ussd_reply(menu.t("unknown_phone", "en"), end=True)
        key = f"ussd:{sessionId}"
        session = await ready.cache.get(key)
        if text == "":
            with spans.start_as_current_span("ussd.session_start") as span:
                span.set_attribute("atra.language", contact.language)
                session = {"language": contact.language}
                await ready.cache.set(key, session, ttl_s=menu.timeout_s)
        elif session is None:
            return ussd_reply(menu.t("timeout", contact.language), end=True)
        inputs = text.split("*") if text else []
        reply, end = await walk("ussd", sessionId, contact, phoneNumber, inputs,
                                str(session["language"]))
        if end:
            await ready.cache.delete(key)
        return ussd_reply(reply, end=end)

    @app.post("/v1/sms/inbound", tags=["sms"])
    async def sms_inbound(from_: Annotated[str, Form(alias="from")], to: Annotated[str, Form()],
                          text: Annotated[str, Form()], id: Annotated[str, Form()],
                          date: Annotated[str, Form()] = "",
                          linkId: Annotated[str, Form()] = "") -> dict[str, str]:
        contact = directory.by_phone(from_)
        await outbox.received("sms", directory.ref(from_), id,
                              language=contact.language if contact else "en",
                              tenant_id=contact.tenant_id if contact else None,
                              hdt_id=contact.hdt_id if contact else None)
        if contact is not None and contact.hdt_id is not None and text.strip():
            step = Step("", True, contact.language, action="ask", data={"text": text.strip()})
            await run_action(step, contact, from_)
        return {"status": "received", "message_id": id}

    @app.post("/v1/sms/delivery", tags=["sms"])
    async def sms_delivery(id: Annotated[str, Form()], status: Annotated[str, Form()],
                           phoneNumber: Annotated[str, Form()] = "",
                           networkCode: Annotated[str, Form()] = "",
                           failureReason: Annotated[str, Form()] = "",
                           retryCount: Annotated[str, Form()] = "") -> dict[str, str]:
        msg = outbox.delivery_report(id, status, failureReason or None)
        return {"status": msg.status if msg else "unknown"}

    @app.post("/v1/voice/callback", tags=["voice"])
    async def voice(sessionId: Annotated[str, Form()], isActive: Annotated[str, Form()],
                    callerNumber: Annotated[str, Form()] = "",
                    direction: Annotated[str, Form()] = "",
                    destinationNumber: Annotated[str, Form()] = "",
                    dtmfDigits: Annotated[str, Form()] = "",
                    durationInSeconds: Annotated[str, Form()] = "") -> Response:
        key = f"voice:{sessionId}"
        if isActive != "1":
            await ready.cache.delete(key)
            return Response(status_code=204)
        contact = directory.by_phone(callerNumber)
        if contact is None or contact.hdt_id is None:
            return Response(VoiceResponse().say(menu.t("unknown_phone", "en")).xml(),
                            media_type="application/xml")
        session = await ready.cache.get(key) or {"language": contact.language, "digits": []}
        if dtmfDigits:
            session["digits"] = [*session["digits"], dtmfDigits.rstrip("#")]
        await ready.cache.set(key, session, ttl_s=menu.timeout_s)
        lang = str(session["language"])
        if menu.walk(session["digits"], lang).node == "ask":
            await ready.cache.delete(key)
            return Response(VoiceResponse().say(menu.t("voice.use_sms", lang)).xml(),
                            media_type="application/xml")
        text, end = await walk("voice", sessionId, contact, callerNumber,
                               list(session["digits"]), lang)
        out = VoiceResponse()
        url = None
        if prompts.has_voice(lang):
            url = f"{settings.services.channels}/v1/voice/audio/{await prompts.prompt(lang, text)}"
        if end:
            await ready.cache.delete(key)
            if url:
                out.play(url)
            else:
                out.say(text)
        else:
            out.get_digits(prompt_text=text, prompt_url=url, num_digits=1, timeout_s=20)
        return Response(out.xml(), media_type="application/xml")

    @app.get("/v1/voice/audio/{key}", tags=["voice"])
    async def voice_audio(key: str) -> Response:
        audio = prompts.audio(key)
        if audio is None:
            raise Problem(404, "not-found", "no such prompt")
        return Response(audio[0], media_type=audio[1])

    @app.post("/v1/sms/send", tags=["sms"])
    async def sms_send(request: Request, body: SendRequest) -> dict[str, str]:
        await service_client(request)
        phone = directory.phone_of(body.to)
        if phone is None:
            raise Problem(404, "not-found", "no phone on record for this person")
        contact = directory.by_phone(phone)
        msg = await outbox.enqueue(phone, body.text, language=body.language,
                                   purpose=body.purpose,
                                   tenant_id=contact.tenant_id if contact else None,
                                   hdt_id=contact.hdt_id if contact else None)
        return {"message_id": msg.message_id, "status": msg.status}

    @app.post("/v1/sms/page", tags=["sms"])
    async def sms_page(request: Request, body: PageRequest) -> dict[str, str]:
        await service_client(request)
        phone = directory.phone_of(body.to.get("id", ""))
        if phone is None:
            raise Problem(404, "not-found", "no phone on record for this clinician")
        msg = await outbox.enqueue(
            phone, f"ATRA {body.severity.upper()} alert {body.alert_id}: {body.reason}",
            language="en", purpose="care", tenant_id=body.tenant_id)
        return {"message_id": msg.message_id, "status": msg.status}

    @app.post("/v1/outbox/flush", tags=["sms"])
    async def outbox_flush(request: Request) -> dict[str, int]:
        await service_client(request)
        tried = await outbox.flush()
        return {"tried": tried, "pending": len(outbox.pending())}

    @app.get("/v1/simulator/inbox", tags=["simulator"])
    async def simulator_inbox(phone: str) -> dict[str, list[str]]:
        if directory.by_phone(phone) is None:
            raise Problem(404, "not-found", "not a simulator phone")
        return {"messages": list(simulated.inbox.get(phone, []))}

    @app.get("/simulator", response_class=HTMLResponse, tags=["simulator"])
    async def simulator() -> str:
        return SIMULATOR.read_text(encoding="utf-8").replace("{{SERVICE_CODE}}",
                                                             menu.service_code)

    return app


def await_list(source: PlanSource, empty: str,
               menu: Menu) -> Callable[[Step, Contact, str], Awaitable[str]]:
    async def run(step: Step, contact: Contact, phone: str) -> str:
        lines = await source(contact)
        return "\n".join(lines) if lines else menu.t(empty, step.language)
    return run
