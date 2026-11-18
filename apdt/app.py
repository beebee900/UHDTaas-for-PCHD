"""APDT service: the Layer 7.4 API of design 03, 3.7 (port 8200).

Routes are served under `/v1/t/{tenant_id}`. Every route verifies the bearer token, asks
OPA (`apdt.routes`) and writes an audit record. Recommendations, bundles, the
unified view, the worklists and goal runs come from `apdt.services`.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Annotated, Any, Literal

import httpx
from fastapi import APIRouter, Body, FastAPI, Path, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from opentelemetry.propagate import extract
from pydantic import BaseModel, Field

from apdt.intake.routes import mount_intake
from apdt.integration.critical import CriticalPager, CriticalRules
from apdt.integration.hie import build_referral
from apdt.integration.inbox import IntegrationInbox
from apdt.integration.routes import mount_integration
from apdt.services import clinical_record, views
from apdt.services.ahdt_access import AHDTAccess
from apdt.services.inputs import MissingInputs
from apdt.services.journal import Journal
from apdt.services.memory_store import InMemoryEpisodeStore, episode_of_care
from apdt.services.recommend import NothingToRecommend, Recommender
from apdt.services.runs import RunService
from apdt.services.write_back import SCOPE as WRITE_BACK_SCOPE
from apdt.services.write_back import AHDTWriteBack
from apdt.xai.bundle import view_for
from atra import contracts as c
from atra.backends import Backends
from atra.config import Settings, get_settings
from atra.consent import ConsentRegistry, demo_registry
from atra.contracts import EventEnvelope
from atra.gateway import CallContext
from atra.ids import uuid7
from atra.kb import KnowledgeBase
from atra.policy import PolicyDecision
from atra.schemagen import APDT_DESCRIPTIONS, service_tool_descriptor
from atra.service import (
    Identity,
    McpMount,
    Problem,
    SkillSpec,
    ToolExecutor,
    authenticate,
    create_app,
    mount_a2a,
    mount_mcp,
    verifier_of,
)
from atra.telemetry import tracer

TenantPath = Annotated[c.TenantId, Path()]
FHIRResource = Annotated[dict[str, Any], Body()]

CDS_SERVICES: list[dict[str, Any]] = [
    {"hook": "patient-view", "id": "apdt-patient-view", "title": "APDT patient summary",
     "description": "AHDT state and open APDT recommendations for the patient",
     "prefetch": {"patient": "Patient/{{context.patientId}}"}},
    {"hook": "order-select", "id": "apdt-order-select", "title": "APDT order check",
     "description": "Interactions, renal and pharmacogenomic dosing for selected orders"},
    {"hook": "order-sign", "id": "apdt-order-sign", "title": "APDT signing check",
     "description": "Final safety check before an order is signed"},
]


class LoginRequest(BaseModel):
    username: str
    password: str = Field(repr=False)


def build_app(settings: Settings | None = None, *, backends: Backends | None = None,
              consents: ConsentRegistry | None = None,
              ahdt_client: httpx.AsyncClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = create_app("apdt", settings, backends=backends, title="APDT",
                     description="Agentic Patient Digital Twin: clinical decision support API")
    ready: Backends = app.state.backends
    app.state.episodes = InMemoryEpisodeStore()
    app.state.consents = consents or demo_registry()
    episodes: InMemoryEpisodeStore = app.state.episodes
    consent_registry: ConsentRegistry = app.state.consents
    ahdt = AHDTAccess(settings.services.ahdt, lambda: ready.issuer.issue_service("apdt-svc"),
                      consent_registry, ahdt_client)
    journal = Journal(ready.relational)

    async def proposed(rec: c.Recommendation) -> None:
        await _event(ready, "recommendation.proposed", rec.model_dump(mode="json"),
                     episodes.episodes.get(rec.episode_id or ""))

    recommender = Recommender(episodes, ahdt, ready.models, journal, proposed)

    async def publish(event_type: str, payload: Mapping[str, Any], ep: c.Episode | None) -> None:
        await _event(ready, event_type, payload, ep)

    write_back = AHDTWriteBack(
        ahdt, lambda: ready.issuer.issue_service("apdt-svc", scopes=(WRITE_BACK_SCOPE,)),
        consent_registry, app.state.audit)
    run_service = RunService(episodes, recommender, journal, app.state.audit, publish,
                             write_back.diagnosis)
    app.state.ahdt_access, app.state.recommender = ahdt, recommender
    app.state.write_back = write_back
    app.state.runs = run_service.runs
    app.state.run_service = run_service
    spans = tracer("apdt")

    def call_context(ident: Identity, ep: c.Episode) -> CallContext:
        return CallContext(ep.hdt_id, ident.ctx.actor_role, ident.ctx.actor_id,
                           ident.ctx.purpose, ep.episode_id, ident.ctx.agent)

    async def check(request: Request, route: str, tenant_id: str,
                    hdt_id: str | None = None, worklist_role: str | None = None) -> Identity:
        ident = await authenticate(dict(request.headers), await verifier_of(app), hdt_id=hdt_id)
        decision = await ready.policy.decide("apdt.routes", {
            "route": route, "role": ident.ctx.actor_role.value, "service": ident.delegated,
            "tenant_id": tenant_id, "hdt_id": hdt_id, "worklist_role": worklist_role,
            "claims": ident.claims.policy_view()})
        app.state.audit.append(
            actor={"id": ident.ctx.actor_id, "role": ident.ctx.actor_role.value},
            tenant_id=tenant_id, hdt_id=hdt_id, action="route", target=route,
            purpose=ident.ctx.purpose, outcome="ok" if decision.allow else "denied",
            reason=None if decision.allow else decision.reason)
        if not decision.allow:
            raise Problem(403, "forbidden", decision.reason or "denied by policy")
        return ident

    def episode(tenant_id: str, eid: str) -> c.Episode:
        try:
            return episodes.get(tenant_id, eid)
        except KeyError:
            raise Problem(404, "not-found", f"no episode {eid} at {tenant_id}") from None

    r = APIRouter(prefix="/v1/t/{tenant_id}", tags=["apdt"])

    @r.post("/episodes", response_model=c.EpisodeView, status_code=201)
    async def create_episode(request: Request, tenant_id: TenantPath,
                             body: c.EpisodeCreate) -> c.EpisodeView:
        ident = await check(request, "episodes.create", tenant_id, body.hdt_id)
        ep = episodes.create(tenant_id, body, ident.ctx.actor_id)
        await _event(ready, "episode.opened", ep.model_dump(mode="json"), ep)
        return c.EpisodeView(episode=ep, episode_of_care=episode_of_care(ep))

    @r.get("/episodes", response_model=list[c.EpisodeListItem])
    async def list_episodes(request: Request, tenant_id: TenantPath,
                            status: Literal["open", "closed", "all"] = "open",
                            hdt_id: str | None = None) -> list[c.EpisodeListItem]:
        await check(request, "episodes.list", tenant_id, hdt_id)
        return [c.EpisodeListItem(episode=ep, patient=views.patient_entry(ep.hdt_id))
                for ep in episodes.list(tenant_id, status)
                if hdt_id is None or ep.hdt_id == hdt_id]

    @r.get("/patients", response_model=list[c.PatientEntry])
    async def list_patients(request: Request, tenant_id: TenantPath) -> list[c.PatientEntry]:
        await check(request, "patients.list", tenant_id)
        return views.facility_patients(tenant_id)

    @r.get("/intake/catalogue", response_model=c.IntakeCatalogue)
    async def intake_catalogue(request: Request, tenant_id: TenantPath) -> c.IntakeCatalogue:
        await check(request, "intake.catalogue", tenant_id)
        return views.intake_catalogue(settings.kb_dir)

    @r.get("/episodes/{episode_id}", response_model=c.EpisodeView)
    async def get_episode(request: Request, tenant_id: TenantPath,
                          episode_id: str) -> c.EpisodeView:
        ep = episode(tenant_id, episode_id)
        await check(request, "episodes.read", tenant_id, ep.hdt_id)
        return c.EpisodeView(episode=ep, episode_of_care=episode_of_care(ep),
                             resources=episodes.resources[ep.episode_id])

    @r.post("/episodes/{episode_id}/close", response_model=c.Episode)
    async def close_episode(request: Request, tenant_id: TenantPath, episode_id: str,
                            body: c.EpisodeClose) -> c.Episode:
        ep = episode(tenant_id, episode_id)
        await check(request, "episodes.close", tenant_id, ep.hdt_id)
        closed = episodes.close(tenant_id, episode_id)
        await _event(ready, "episode.closed", closed.model_dump(mode="json"), closed)
        return closed

    @r.post("/episodes/{episode_id}/resources", status_code=201)
    async def add_resource(request: Request, tenant_id: TenantPath, episode_id: str,
                           resource: FHIRResource) -> dict[str, Any]:
        ep = episode(tenant_id, episode_id)
        await check(request, "episodes.resources", tenant_id, ep.hdt_id)
        if resource.get("resourceType") not in _L1_RESOURCES:
            raise Problem(422, "invalid-request",
                          f"resourceType must be one of {sorted(_L1_RESOURCES)}")
        return episodes.add_resource(tenant_id, episode_id, resource)

    @r.post("/episodes/{episode_id}/intake", response_model=c.EpisodeView, status_code=201)
    async def record_intake(request: Request, tenant_id: TenantPath, episode_id: str,
                            body: c.IntakeRecord) -> c.EpisodeView:
        ep = episode(tenant_id, episode_id)
        await check(request, "episodes.resources", tenant_id, ep.hdt_id)
        try:
            resources = views.intake_resources(ep.hdt_id, tenant_id, body,
                                               views.intake_catalogue(settings.kb_dir))
        except ValueError as exc:
            raise Problem(422, "invalid-request", str(exc)) from exc
        for resource in resources:
            episodes.add_resource(tenant_id, episode_id, resource)
        return c.EpisodeView(episode=ep, episode_of_care=episode_of_care(ep),
                             resources=episodes.resources[ep.episode_id])

    @r.get("/episodes/{episode_id}/record", response_model=list[c.ClinicalEntry])
    async def get_record(request: Request, tenant_id: TenantPath,
                         episode_id: str) -> list[c.ClinicalEntry]:
        """The diagnoses, dispenses and care given that clinicians entered, newest first."""
        ep = episode(tenant_id, episode_id)
        await check(request, "record.read", tenant_id, ep.hdt_id)
        return clinical_record.entries(episodes.resources[ep.episode_id])

    async def enter(request: Request, tenant_id: str, episode_id: str,
                    kind: clinical_record.Kind, build: Any, body: Any) -> c.ClinicalEntry:
        ep = episode(tenant_id, episode_id)
        ident = await check(request, f"record.{kind}", tenant_id, ep.hdt_id)
        if ep.status != "open":
            raise Problem(422, "invalid-request", f"episode {episode_id} is closed")
        actor = c.Actor(id=ident.ctx.actor_id, role=ident.ctx.actor_role.value)
        stored = episodes.add_resource(tenant_id, episode_id, build(body, ep.hdt_id, actor))
        entry = clinical_record.entry_of(stored)
        assert entry is not None
        await _event(ready, f"record.{kind}", entry.model_dump(mode="json"), ep)
        return entry

    @r.post("/episodes/{episode_id}/record/diagnosis", response_model=c.ClinicalEntry,
            status_code=201)
    async def record_diagnosis(request: Request, tenant_id: TenantPath, episode_id: str,
                               body: c.DiagnosisEntry) -> c.ClinicalEntry:
        """The medical officer's diagnosis."""
        return await enter(request, tenant_id, episode_id, "diagnosis",
                           clinical_record.diagnosis_resource, body)

    @r.post("/episodes/{episode_id}/record/dispense", response_model=c.ClinicalEntry,
            status_code=201)
    async def record_dispense(request: Request, tenant_id: TenantPath, episode_id: str,
                              body: c.DispenseEntry) -> c.ClinicalEntry:
        """A medication the pharmacist dispensed."""
        return await enter(request, tenant_id, episode_id, "dispense",
                           clinical_record.dispense_resource, body)

    @r.post("/episodes/{episode_id}/record/administration", response_model=c.ClinicalEntry,
            status_code=201)
    async def record_administration(request: Request, tenant_id: TenantPath, episode_id: str,
                                    body: c.AdministrationEntry) -> c.ClinicalEntry:
        """A medication the nurse gave or care the nurse carried out."""
        return await enter(request, tenant_id, episode_id, "administration",
                           clinical_record.administration_resource, body)

    latest_runs: dict[tuple[str, str], str] = {}
    for goal in ("diagnosis", "treatment", "care"):
        _add_goal_route(r, goal, check, episode, run_service, call_context, latest_runs)

    @r.get("/runs/{run_id}", response_model=c.RunStatus)
    async def get_run(request: Request, tenant_id: TenantPath, run_id: str) -> c.RunStatus:
        await check(request, "runs.read", tenant_id)
        if run_id not in run_service.runs:
            raise Problem(404, "not-found", f"no run {run_id}")
        return run_service.runs[run_id]

    @r.post("/runs/{run_id}/resume", response_model=c.RunStatus)
    async def resume_run(request: Request, tenant_id: TenantPath, run_id: str,
                         decision: c.ClinicalDecision) -> c.RunStatus:
        ident = await check(request, "runs.resume", tenant_id)
        return await run_service.resume(run_id, decision, ident, tenant_id)

    @r.get("/episodes/{episode_id}/recommendations", response_model=list[c.Recommendation])
    async def recommendations(request: Request, tenant_id: TenantPath,
                              episode_id: str) -> list[c.Recommendation]:
        ep = episode(tenant_id, episode_id)
        ident = await check(request, "recommendations.read", tenant_id, ep.hdt_id)
        try:
            return await recommender.for_episode(ep, call_context(ident, ep))
        except (MissingInputs, NothingToRecommend):
            return list(episodes.recommendations[ep.episode_id])

    @r.get("/bundles/{bundle_id}", response_model=c.ExplanationBundle)
    async def get_bundle(request: Request, tenant_id: TenantPath, bundle_id: str,
                         audience: str = Query("medical_officer")) -> c.ExplanationBundle:
        bundle = episodes.bundles.get(bundle_id)
        if bundle is None:
            raise Problem(404, "not-found", f"no bundle {bundle_id}")
        rec = episodes.recommendation(bundle.recommendation_id)
        episode(tenant_id, rec.episode_id or "")
        ident = await check(request, "bundles.read", tenant_id, rec.hdt_id)
        if ident.ctx.actor_role in (c.Role.PATIENT, c.Role.PROXY, c.Role.PERSON):
            audience = "patient"
        if audience not in bundle.audience_views:
            raise Problem(422, "invalid-request", f"no {audience} view of this bundle")
        return view_for(bundle, audience)

    @r.get("/episodes/{episode_id}/unified-view", response_model=c.UnifiedView)
    async def get_unified(request: Request, tenant_id: TenantPath,
                          episode_id: str) -> c.UnifiedView:
        ep = episode(tenant_id, episode_id)
        ident = await check(request, "unified_view.read", tenant_id, ep.hdt_id)
        return await views.unified_view(ep, episodes, ahdt, call_context(ident, ep))

    @r.get("/episodes/{episode_id}/ahdt-panel", response_model=c.AHDTPanel)
    async def get_panel(request: Request, tenant_id: TenantPath, episode_id: str) -> c.AHDTPanel:
        ep = episode(tenant_id, episode_id)
        ident = await check(request, "ahdt_panel.read", tenant_id, ep.hdt_id)
        return await views.ahdt_panel(ep, ahdt, call_context(ident, ep))

    @r.put("/patients/{hdt_id}/consent", response_model=c.ConsentData)
    async def put_consent(request: Request, tenant_id: TenantPath, hdt_id: str,
                          resource: FHIRResource) -> c.ConsentData:
        await check(request, "consent.write", tenant_id, hdt_id)
        if resource.get("resourceType") != "Consent":
            raise Problem(422, "invalid-request", "the body must be a FHIR Consent")
        if str(resource.get("patient", {}).get("reference", "")).split("/")[-1] != hdt_id:
            raise Problem(422, "invalid-request", "the Consent is for another patient")
        with spans.start_as_current_span("apdt.consent.store",
                                         context=extract(dict(request.headers))):
            stored = await _store_consent(ready, tenant_id, resource)
            with spans.start_as_current_span("apdt.gateway.consent_update"):
                consent = consent_registry.apply_fhir(stored)
        resource = stored
        await _event(ready, "consent.changed", {"hdt_id": hdt_id, "consent_id": resource.get("id"),
                                                "purposes": sorted(consent.purposes),
                                                "refused_tools": sorted(consent.refused_tools)},
                     None, hdt_id=hdt_id)
        return c.ConsentData(hdt_id=hdt_id, purposes=sorted(consent.purposes),
                             refused_tools=sorted(consent.refused_tools),
                             consent_id=resource.get("id"))

    @r.get("/patients/{hdt_id}/consent", response_model=c.ConsentData)
    async def get_consent(request: Request, tenant_id: TenantPath, hdt_id: str
                          ) -> c.ConsentData:
        await check(request, "consent.read", tenant_id, hdt_id)
        consent = consent_registry.get(hdt_id)
        if consent is None:
            raise Problem(404, "not-found", f"no consent on record for {hdt_id}")
        return c.ConsentData(hdt_id=hdt_id, purposes=sorted(consent.purposes),
                             refused_tools=sorted(consent.refused_tools))

    @r.put("/patients/{hdt_id}/preferences", response_model=c.PreferenceWeights)
    async def put_preferences(request: Request, tenant_id: TenantPath, hdt_id: str,
                              body: c.Preferences) -> c.PreferenceWeights:
        await check(request, "preferences.write", tenant_id, hdt_id)
        n = max(len(body.answers), 1)
        return c.PreferenceWeights(hdt_id=hdt_id, weights={k: 1 / n for k in body.answers})

    @r.post("/patients/{hdt_id}/messages", response_model=c.PatientReply)
    async def post_message(request: Request, tenant_id: TenantPath, hdt_id: str,
                           body: c.PatientMessage) -> c.PatientReply:
        await check(request, "messages.create", tenant_id, hdt_id)
        return c.PatientReply(reply="Your care team has your message.", language=body.language)

    @r.get("/worklists/{role}", response_model=c.Worklist)
    async def get_worklist(request: Request, tenant_id: TenantPath, role: c.Role) -> c.Worklist:
        await check(request, "worklists.read", tenant_id, worklist_role=role.value)
        return views.worklist(role, tenant_id, episodes)

    @r.post("/alerts/{alert_id}/ack", response_model=c.AlertAckResult)
    async def ack_alert(request: Request, tenant_id: TenantPath, alert_id: str,
                        body: c.AlertAck) -> c.AlertAckResult:
        await check(request, "alerts.ack", tenant_id)
        await _event(ready, "alert.acknowledged", {"alert_id": alert_id, "by": body.by}, None)
        return c.AlertAckResult(alert_id=alert_id, acknowledged_by=body.by,
                                acknowledged_at=datetime.now(UTC))

    @r.post("/referrals", response_model=c.ReferralResult, status_code=201)
    async def post_referral(request: Request, tenant_id: TenantPath,
                            body: c.ReferralRequest) -> c.ReferralResult:
        ep = episode(tenant_id, body.episode_id)
        ident = await check(request, "referrals.create", tenant_id, ep.hdt_id)
        bundle = build_referral(ep.hdt_id, episodes.resources[ep.episode_id],
                                from_tenant=tenant_id, to_tenant=body.to_tenant,
                                reason=body.reason, requester=ident.ctx.actor_id,
                                urgency=body.urgency)
        rid = str(bundle["identifier"]["value"])
        ref = f"referrals/{rid}.json"
        target = settings.var_dir / ref
        target.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_text, json.dumps(bundle, indent=1),
                                encoding="utf-8")
        app.state.audit.append(
            actor={"id": ident.ctx.actor_id, "role": ident.ctx.actor_role.value},
            tenant_id=tenant_id, hdt_id=ep.hdt_id, episode_id=ep.episode_id,
            action="referral.create", target=rid, purpose=ident.ctx.purpose, outcome="ok")
        await _event(ready, "referral.queued", {"referral_id": rid, "bundle_ref": ref,
                                                "to_tenant": body.to_tenant}, ep)
        return c.ReferralResult(referral_id=rid, bundle_ref=ref, status="queued")

    @r.get("/audit", response_model=list[c.AuditRecord])
    async def get_audit(request: Request, tenant_id: TenantPath,
                        episode_id: str | None = None, hdt_id: str | None = None,
                        limit: Annotated[int, Query(ge=1, le=1000)] = 200
                        ) -> list[c.AuditRecord]:
        """The facility's audit records, newest first."""
        await check(request, "audit.read", tenant_id)
        found = [rec for rec in app.state.audit if rec.tenant_id == tenant_id
                 and (episode_id is None or rec.episode_id == episode_id)
                 and (hdt_id is None or rec.hdt_id == hdt_id)]
        return found[::-1][:limit]

    @r.websocket("/stream")
    async def stream(websocket: WebSocket, tenant_id: str, episode_id: str | None = None,
                     access_token: str | None = None) -> None:
        try:
            ident = await authenticate({"authorization": f"Bearer {access_token}"},
                                       await verifier_of(app))
        except Problem:
            await websocket.close(code=4401)
            return
        if ident.tenant_id not in (None, tenant_id):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue(maxsize=100)

        async def forward(event: EventEnvelope) -> None:
            wanted = event.tenant_id in (None, tenant_id) and (
                episode_id is None or event.episode_id == episode_id)
            if wanted and not queue.full():
                queue.put_nowait(event)

        ready.events.subscribe("*", forward)
        try:
            while True:
                event = await queue.get()
                await websocket.send_text(event.model_dump_json())
        except WebSocketDisconnect:
            return

    app.include_router(r)
    mount_integration(app, _integration_inbox(app, settings))
    mount_intake(app, check)
    _mount_standards(app)
    _mount_auth(app, settings)
    _mount_mcp_tools(app, check)
    base = settings.services.apdt
    mount_a2a(app, base, "apdt-patient-agent", "The patient's own agent in the APDT",
              (SkillSpec("episode_status", "Status of the patient's open episode"),
               SkillSpec("request_ahdt_goal", "Ask the AHDT conductor to pursue a goal")),
              _patient_agent(episodes), version="1.0.0")
    mount_a2a(app, base, "apdt-referral", "Receives referrals from other facilities",
              (SkillSpec("receive_referral", "Accept a referral bundle"),),
              _referral_skill, version="1.0.0")
    return app


_L1_RESOURCES = frozenset({
    "QuestionnaireResponse", "Observation", "Condition", "ClinicalImpression", "ServiceRequest",
    "DiagnosticReport", "ImagingStudy", "Specimen", "MedicationRequest", "MedicationDispense",
    "DetectedIssue", "CarePlan", "Task", "Goal", "Encounter", "Consent"})


def _add_goal_route(r: APIRouter, goal: str, check: Any, episode: Any, runs: RunService,
                    call_context: Any, latest: dict[tuple[str, str], str]) -> None:
    async def start(request: Request, tenant_id: TenantPath, episode_id: str) -> c.RunStarted:
        ep = episode(tenant_id, episode_id)
        ident = await check(request, f"goals.{goal}", tenant_id, ep.hdt_id)
        # A run that waits for a human is the one every clinician of the episode continues:
        # the pharmacist verifies in the run the medical officer signed.
        waiting = runs.runs.get(latest.get((ep.episode_id, goal), ""))
        if waiting is not None and waiting.status == "waiting_for_human":
            return c.RunStarted(run_id=waiting.run_id, goal=goal)
        started = await runs.start(goal, ep, call_context(ident, ep))
        latest[(ep.episode_id, goal)] = started.run_id
        return started

    r.add_api_route(f"/episodes/{{episode_id}}/goals/{goal}", start, methods=["POST"],
                    response_model=c.RunStarted, status_code=202, name=f"start_{goal}")


async def _store_consent(backends: Backends, tenant_id: str,
                         resource: Mapping[str, Any]) -> dict[str, Any]:
    """The FHIR Consent in the tenant's partition, replacing an earlier version."""
    body = {**resource, "id": resource.get("id") or f"consent-{uuid7()}"}
    try:
        return await backends.fhir.create(body, partition=tenant_id)
    except FileExistsError:
        return await backends.fhir.update(body, partition=tenant_id)


async def _event(backends: Backends, event_type: str, payload: Mapping[str, Any],
                 ep: c.Episode | None, *, hdt_id: str | None = None) -> None:
    await backends.events.publish(EventEnvelope(
        event_id=f"evt-{uuid7()}", event_type=event_type, source="apdt",
        hdt_id=ep.hdt_id if ep else hdt_id, tenant_id=ep.tenant_id if ep else None,
        episode_id=ep.episode_id if ep else None, wall_time=datetime.now(UTC),
        trace_id=uuid7().hex, payload=dict(payload)))


def _integration_inbox(app: FastAPI, settings: Settings) -> IntegrationInbox:
    """The integration inbox, paging critical results as `alert.raised` with an SMS page
    through the channels service."""
    backends: Backends = app.state.backends

    async def sms_page(alert: Mapping[str, Any]) -> None:
        token = backends.issuer.issue_service("apdt-svc")
        try:
            async with httpx.AsyncClient(base_url=settings.services.channels, timeout=10) as h:
                await h.post("/v1/sms/page", json=dict(alert),
                             headers={"authorization": f"Bearer {token}"})
        except httpx.HTTPError as exc:
            app.state.audit.append(actor={"id": "apdt", "role": "system"}, action="sms.page",
                                   target=str(alert["alert_id"]), purpose="care",
                                   outcome="degraded", reason=str(exc))

    pager = CriticalPager(backends, CriticalRules(KnowledgeBase(settings.kb_dir)),
                          sms_page=sms_page)
    return IntegrationInbox(backends.fhir, app.state.audit, pager=pager)


def _mount_standards(app: FastAPI) -> None:
    @app.get("/cds-services", tags=["cds-hooks"])
    async def cds_discovery() -> dict[str, Any]:
        return {"services": CDS_SERVICES}

    @app.post("/cds-services/{service_id}", tags=["cds-hooks"])
    async def cds_service(service_id: str, body: dict[str, Any]) -> dict[str, Any]:
        if service_id not in {s["id"] for s in CDS_SERVICES}:
            raise Problem(404, "not-found", f"no CDS service {service_id}")
        return {"cards": [{"uuid": str(uuid7()), "summary": "APDT: no new suggestions",
                           "indicator": "info", "source": {"label": "APDT"}}]}

    @app.get("/smart/.well-known/smart-configuration", tags=["smart"])
    async def smart_configuration() -> dict[str, Any]:
        base = app.state.settings.services.apdt
        return {"issuer": app.state.settings.security.issuer,
                "jwks_uri": f"{base}/.well-known/jwks.json",
                "authorization_endpoint": f"{base}/smart/authorize",
                "token_endpoint": f"{base}/auth/token",
                "grant_types_supported": ["authorization_code", "client_credentials"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": ["openid", "fhirUser", "launch", "launch/patient",
                                     "offline_access", "patient/*.rs", "user/*.cruds",
                                     "system/*.rs"],
                "capabilities": ["launch-ehr", "launch-standalone", "client-public",
                                 "client-confidential-asymmetric", "context-ehr-patient",
                                 "context-standalone-patient", "permission-patient",
                                 "permission-user", "sso-openid-connect"]}

    @app.get("/smart/launch", tags=["smart"])
    async def smart_launch(iss: str, launch: str) -> dict[str, Any]:
        return {"iss": iss, "launch": launch, "next": "/smart/authorize"}


def _mount_auth(app: FastAPI, settings: Settings) -> None:
    """Local issuer login (profile p0); Keycloak serves logins in p2."""
    from atra.demo_users import UserStore

    @app.post("/auth/token", tags=["auth"])
    async def token(body: LoginRequest) -> JSONResponse:
        if settings.backend.identity != "memory":
            raise Problem(404, "not-found", "log in through Keycloak")
        user = UserStore(settings.var_dir / "keys" / "demo-users.json").check(
            body.username, body.password)
        if user is None:
            raise Problem(401, "unauthenticated", "unknown user or wrong password")
        scopes = (["patient/*.rs", "openid", "fhirUser"] if user.hdt_id or user.proxy_for
                  else ["user/*.cruds", "openid", "fhirUser"])
        access = app.state.backends.issuer.issue(
            user.username, user.role, tenant_id=user.tenant_id, hdt_id=user.hdt_id,
            proxy_for=user.proxy_for, carer_for=user.carer_for, scopes=scopes)
        return JSONResponse({"access_token": access, "token_type": "Bearer",
                             "expires_in": settings.security.token_ttl_s,
                             "role": user.role.value, "tenant_id": user.tenant_id,
                             "hdt_id": user.hdt_id})


def _mount_mcp_tools(app: FastAPI, check: Any) -> None:
    episodes: InMemoryEpisodeStore = app.state.episodes
    recommender: Recommender = app.state.recommender
    consents: ConsentRegistry = app.state.consents

    async def authorise(tool: str, args: BaseModel, ident: Identity) -> PolicyDecision:
        a: Any = args
        hdt_id = getattr(a, "hdt_id", None)
        if hdt_id is None and getattr(a, "episode_id", None):
            ep = episodes.episodes.get(a.episode_id)
            hdt_id = ep.hdt_id if ep else None
        policy: Any = app.state.backends.policy
        return await policy.decide("apdt.routes", {  # type: ignore[no-any-return]
            "route": tool, "role": ident.ctx.actor_role.value, "service": ident.delegated,
            "tenant_id": a.tenant_id, "hdt_id": hdt_id, "claims": ident.claims.policy_view()})

    async def recommended(args: BaseModel, ident: Identity) -> tuple[c.Episode, list[Any]]:
        a: Any = args
        ep = episodes.get(a.tenant_id, a.episode_id)
        ctx = CallContext(ep.hdt_id, ident.ctx.actor_role, ident.ctx.actor_id,
                          ident.ctx.purpose, ep.episode_id, ident.ctx.agent)
        try:
            return ep, await recommender.for_episode(ep, ctx)
        except (MissingInputs, NothingToRecommend):
            return ep, list(episodes.recommendations[ep.episode_id])

    async def summary(args: BaseModel, ident: Identity) -> dict[str, Any]:
        ep, recs = await recommended(args, ident)
        diagnosis = next((r for r in recs if r.kind == "diagnosis"), None)
        care = next((r for r in recs if r.kind == "care"), None)
        ews = (care.payload.get("early_warning") or {}) if care else {}
        return {"episode": ep.model_dump(mode="json"),
                "problems": [diagnosis.payload["code"]] if diagnosis and diagnosis.payload["code"]
                else [],
                "active_medications": [r["medicationCodeableConcept"]["text"]
                                       for r in episodes.resources[ep.episode_id]
                                       if r["resourceType"] == "MedicationRequest"],
                "open_recommendations": [r.recommendation_id for r in recs
                                         if r.status == "proposed"],
                "latest_news2": ews.get("total") if ews.get("scale") == "NEWS2" else None}

    async def differential(args: BaseModel, ident: Identity) -> dict[str, Any]:
        _, recs = await recommended(args, ident)
        diagnosis = next((r for r in recs if r.kind == "diagnosis"), None)
        entries = [{"code": d["code"], "probability": d["probability"],
                    "recommendation_id": diagnosis.recommendation_id,
                    "bundle_id": diagnosis.bundle_id}
                   for d in (diagnosis.payload["differential"] if diagnosis else [])
                   if d["code"] and diagnosis is not None][:getattr(args, "top_k", 5)]
        return {"differential": entries, "conformal_set": []}

    async def options(args: BaseModel, ident: Identity) -> dict[str, Any]:
        a: Any = args
        _, recs = await recommended(args, ident)
        out = []
        for rec in (r for r in recs if r.kind == "treatment"):
            bundle = episodes.bundles.get(rec.bundle_id or "")
            diagnosis = next((r for r in recs if r.kind == "diagnosis"), None)
            code = next((d["code"]["code"] for d in diagnosis.payload["differential"]
                         if d["condition"] == rec.payload["condition"] and d["code"]), None) \
                if diagnosis else None
            if bundle is None or code != a.diagnosis_code:
                continue
            out.append({"text": bundle.recommendation.text,
                        "atc": [d["atc"] for d in rec.payload["doses"] if d["atc"]],
                        "score": rec.confidence,
                        "guideline_concordant": rec.payload["preference"] == "first_line",
                        "recommendation_id": rec.recommendation_id,
                        "bundle_id": rec.bundle_id})
        return {"options": out}

    async def explain(args: BaseModel, ident: Identity) -> dict[str, Any]:
        a: Any = args
        bundle = episodes.bundles.get(a.bundle_id)
        if bundle is None:
            raise Problem(404, "not-found", f"no bundle {a.bundle_id}")
        rec = episodes.recommendation(bundle.recommendation_id)
        episodes.get(a.tenant_id, rec.episode_id or "")
        return view_for(bundle, a.audience if a.audience in bundle.audience_views
                        else "medical_officer").model_dump(mode="json")

    async def consent_get(args: BaseModel, ident: Identity) -> dict[str, Any]:
        a: Any = args
        consent = consents.get(a.hdt_id)
        return {"hdt_id": a.hdt_id, "purposes": sorted(consent.purposes) if consent else [],
                "refused_tools": sorted(consent.refused_tools) if consent else []}

    async def verifier() -> Any:
        return await verifier_of(app)

    executor = ToolExecutor(
        service="apdt", version="1.0.0", args=c.APDT_TOOL_ARGS, responses=c.APDT_TOOL_RESPONSES,
        handlers={"apdt.episode.summary": summary, "apdt.diagnosis.differential": differential,
                  "apdt.treatment.options": options, "apdt.explain": explain,
                  "apdt.consent.get": consent_get},
        authorise=authorise, audit=app.state.audit, verifier=verifier,
        descriptions=APDT_DESCRIPTIONS)
    app.state.executor = executor
    descriptors = {n: service_tool_descriptor(n, APDT_DESCRIPTIONS[n], a, c.APDT_TOOL_RESPONSES[n])
                   for n, a in c.APDT_TOOL_ARGS.items()}
    mount_mcp(app, "/mcp/apdt", McpMount("apdt", executor, list(c.APDT_TOOL_ARGS), descriptors))


def _patient_agent(episodes: InMemoryEpisodeStore) -> Any:
    async def handle(skill: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if skill == "episode_status":
            hdt_id = str(args.get("hdt_id", ""))
            open_eps = [e.model_dump(mode="json") for e in episodes.episodes.values()
                        if e.hdt_id == hdt_id and e.status == "open"]
            return {"hdt_id": hdt_id, "open_episodes": open_eps}
        return {"forwarded": True, "goal": json.loads(json.dumps(args.get("goal", {})))}

    return handle


async def _referral_skill(skill: str, args: Mapping[str, Any]) -> dict[str, Any]:
    return {"accepted": True, "referral_id": str(args.get("referral_id", f"ref-{uuid7()}"))}
