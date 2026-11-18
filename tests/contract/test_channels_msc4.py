"""MSC4 (consent over USSD, UC10) through the channels service and the APDT, and the other
channel routes (WP20 acceptance 2, service level; the browser run is tests/e2e)."""

import httpx
import pytest

from apdt.app import build_app as build_apdt
from apdt.records.episodes import EpisodeRecord
from atra.personas import BY_KEY
from atra.telemetry import span_store
from channels.apdt_client import ApdtClient
from channels.app import build_app as build_channels

AO = BY_KEY["ao"]
PHONE = "+2340000000001"
MSC4 = ["ussd.session_start", "communication.data_uses", "communication.consent_decision",
        "apdt.consent.store", "apdt.gateway.consent_update", "communication.confirmation_sms"]


@pytest.fixture
def stack(settings, backends):
    apdt = build_apdt(settings, backends=backends("apdt"))
    issuer = apdt.state.backends.issuer
    client = ApdtClient("http://apdt", lambda: issuer.issue_service("channels-svc"),
                        transport=httpx.ASGITransport(app=apdt))
    channels = build_channels(settings, backends=backends("channels"), apdt=client)
    return apdt, channels


def ussd_client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ch")


def consent_inputs(channels, withhold=("genome",)):
    items = channels.state.menu.consent_items
    return ["5", "1", *["2" if i["id"] in withhold else "1" for i in items], "1"]


async def dial(h, session, inputs):
    replies = []
    for n in range(len(inputs) + 1):
        resp = await h.post("/v1/ussd", data={"sessionId": session, "serviceCode": "*347#",
                                              "phoneNumber": PHONE, "networkCode": "99999",
                                              "text": "*".join(inputs[:n])})
        assert resp.status_code == 200
        replies.append(resp.text)
    return replies


async def test_msc4_consent_over_ussd(stack):
    apdt, channels = stack
    span_store().clear()
    async with ussd_client(channels) as h:
        replies = await dial(h, "sess-msc4", consent_inputs(channels))
    assert replies[0].startswith("CON ") and replies[1].startswith("CON Your record")
    assert replies[-2].startswith("CON You withhold: Genome")
    assert replies[-1] == "END " + channels.state.menu.t("consent.saved", "yo")
    consent = apdt.state.consents.get(AO.hdt_id)
    assert "ahdt.data.genome" in consent.refused_tools and "care" in consent.purposes
    stored = await apdt.state.backends.fhir.search("Consent", partition=AO.tenant_id)
    assert len(stored) == 1 and stored[0]["patient"]["reference"] == f"Patient/{AO.hdt_id}"
    assert channels.state.simulated_sms.inbox[PHONE] == [
        channels.state.menu.t("consent.sms", "yo")]
    events = [e.event_type for e in apdt.state.backends.events.published]
    assert "consent.changed" in events
    spans = sorted((s for s in span_store().get_finished_spans() if s.name in MSC4),
                   key=lambda s: s.start_time)
    assert [s.name for s in spans] == MSC4
    store = next(s for s in spans if s.name == "apdt.consent.store")
    decision = next(s for s in spans if s.name == "communication.consent_decision")
    assert store.context.trace_id == decision.context.trace_id
    audit = channels.state.audit
    assert len(audit.query(action="ussd.request")) == len(replies)
    assert audit.query(action="sms.send")[0].outcome == "ok"
    assert all(PHONE not in r.model_dump_json() for r in audit)
    route = apdt.state.audit.query(target="consent.write")
    assert route and route[-1].outcome == "ok"


async def test_session_timeout_and_unknown_phone(stack):
    _, channels = stack
    async with ussd_client(channels) as h:
        late = await h.post("/v1/ussd", data={"sessionId": "never-started", "serviceCode": "*347#",
                                              "phoneNumber": PHONE, "text": "5"})
        assert late.text.startswith("END ") and "session has ended" in late.text
        stranger = await h.post("/v1/ussd", data={"sessionId": "s", "serviceCode": "*347#",
                                                  "phoneNumber": "+2349999999999", "text": ""})
        assert stranger.text.startswith("END This phone number is not registered")


async def test_check_in_over_ussd_files_a_questionnaire_response(stack):
    apdt, channels = stack
    record = EpisodeRecord(apdt.state.backends.fhir, AO.tenant_id)
    ep = await record.open(AO.hdt_id, reason="Fever")
    n = len(channels.state.menu.questions["check_in"])
    async with ussd_client(channels) as h:
        replies = await dial(h, "sess-check", ["3", "1", *["2"] * (n - 1)])
    assert replies[-1] == "END " + channels.state.menu.t("check_in.done", "yo")
    [qr] = await record.resources(ep["id"], "QuestionnaireResponse")
    assert qr["questionnaire"].endswith("/check-in")
    assert {i["linkId"] for i in qr["item"]} >= {"overall", "took_medicines", "danger_signs"}


async def test_voice_ivr_runs_the_same_menu(stack):
    _, channels = stack
    async with ussd_client(channels) as h:
        first = await h.post("/v1/voice/callback", data={
            "sessionId": "call-1", "isActive": "1", "callerNumber": PHONE,
            "direction": "Inbound", "destinationNumber": "+2340000000999"})
        assert "<GetDigits" in first.text and "Welcome" in first.text
        lang = await h.post("/v1/voice/callback", data={
            "sessionId": "call-1", "isActive": "1", "callerNumber": PHONE, "dtmfDigits": "1"})
        assert "Choose your language" in lang.text
        end = await h.post("/v1/voice/callback", data={
            "sessionId": "call-1", "isActive": "0", "callerNumber": PHONE,
            "durationInSeconds": "30"})
        assert end.status_code == 204


async def test_service_routes_page_and_send(stack):
    _, channels = stack
    token = channels.state.backends.issuer.issue_service("apdt-svc")
    auth = {"authorization": f"Bearer {token}"}
    async with ussd_client(channels) as h:
        page = await h.post("/v1/sms/page", headers=auth, json={
            "alert_id": "alert-1", "severity": "emergency", "reason": "critical potassium 7",
            "to": {"role": "medical_officer", "id": "medical_officer.fac-a"},
            "tenant_id": "fac-a"})
        assert page.status_code == 200 and page.json()["status"] == "sent"
        sent = await h.post("/v1/sms/send", headers=auth,
                            json={"to": AO.hdt_id, "text": "Reminder", "language": "yo"})
        assert sent.status_code == 200
        assert (await h.post("/v1/sms/send", json={"to": AO.hdt_id, "text": "x"})).status_code \
            == 401
        inbox = await h.get("/v1/simulator/inbox", params={"phone": PHONE})
        assert inbox.json()["messages"] == ["Reminder"]
        html = await h.get("/simulator")
        assert 'data-testid="screen"' in html.text and "*347#" in html.text
