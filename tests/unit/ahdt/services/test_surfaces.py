import httpx

from atra.contracts import Role
from atra.personas import BY_KEY
from tests.contract.fixtures import HDT, T0
from tests.unit.ahdt.services.conftest import token


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://ahdt")


def bearer(tok, **headers):
    return {"Authorization": f"Bearer {tok}", **headers}


async def test_fhir_search_is_read_only_and_limited_to_one_person(http):
    mo = bearer(token(http, Role.MEDICAL_OFFICER))
    async with client(http) as c:
        resp = await c.get("/v1/fhir/MedicationStatement", params={"patient": HDT}, headers=mo)
        assert resp.status_code == 200 and resp.json()["total"] == 1
        one = await c.get("/v1/fhir/Condition/cond-malaria", headers=mo)
        assert one.status_code == 200 and one.json()["id"] == "cond-malaria"
        assert (await c.get("/v1/fhir/Condition", headers=mo)).status_code == 400
        assert (await c.post("/v1/fhir/Condition", headers=mo, json={})).status_code == 405
        assert (await c.get("/v1/fhir/Condition/nope", headers=mo)).status_code == 404
        lab = bearer(token(http, Role.PUBLIC_HEALTH_OFFICIAL))
        assert (await c.get("/v1/fhir/Condition", params={"patient": HDT},
                            headers=lab)).status_code == 403


async def test_fhir_service_clients_need_a_smart_scope(http):
    issuer = http.state.backends.issuer
    headers = {"X-Actor-Role": "medical_officer", "X-Actor-Id": "mo-1", "X-Purpose-Of-Use": "care"}
    async with client(http) as c:
        ok = bearer(issuer.issue_service("apdt", scopes=["system/Condition.rs"]), **headers)
        assert (await c.get("/v1/fhir/Condition", params={"patient": HDT},
                            headers=ok)).status_code == 200
        no = bearer(issuer.issue_service("apdt", scopes=["system/Observation.rs"]), **headers)
        assert (await c.get("/v1/fhir/Condition", params={"patient": HDT},
                            headers=no)).status_code == 403


async def test_a_person_reads_only_their_own_record(http):
    own = bearer(token(http, Role.PERSON, hdt_id=HDT))
    other = bearer(token(http, Role.PERSON, hdt_id=BY_KEY["bm"].hdt_id))
    async with client(http) as c:
        assert (await c.get("/v1/fhir/Condition", params={"patient": HDT},
                            headers=own)).status_code == 200
        assert (await c.get("/v1/fhir/Condition", params={"patient": HDT},
                            headers=other)).status_code == 403


async def test_graphql_resolves_through_the_tools(http):
    query = (f'{{ person(hdtId: "{HDT}") {{ medications(activeOnly: true) '
             'observations(codes: ["8310-5"]) { code points { unit } } '
             'twins(kinds: ["cardiovascular"]) { kind status } } }')
    mo = bearer(token(http, Role.MEDICAL_OFFICER))
    async with client(http) as c:
        resp = await c.post("/graphql", json={"query": query}, headers=mo)
    body = resp.json()
    assert "errors" not in body, body
    person = body["data"]["person"]
    assert person["medications"][0]["atc"] == "P01BF01"
    assert len(person["observations"][0]["points"]) == 36
    assert person["twins"][0]["kind"] == "cardiovascular"


async def test_graphql_errors_carry_the_policy_decision(http):
    query = f'{{ person(hdtId: "{HDT}") {{ medications }} }}'
    lab = bearer(token(http, Role.PUBLIC_HEALTH_OFFICIAL))
    async with client(http) as c:
        body = (await c.post("/graphql", json={"query": query}, headers=lab)).json()
    assert body["errors"] and "forbidden" in body["errors"][0]["message"]


async def test_dapr_events_enter_the_in_process_bus(http):
    seen = []

    async def handler(event):
        seen.append(event)

    http.state.backends.events.subscribe("notification.*", handler)
    event = {"event_id": "e1", "event_type": "notification.requested", "source": "ahdt.notify",
             "hdt_id": HDT, "wall_time": T0.isoformat(), "trace_id": "t1",
             "payload": {"channel": "app"}}
    async with client(http) as c:
        resp = await c.post("/dapr/events/notification.requested",
                            json={"specversion": "1.0", "data": event})
        assert resp.status_code == 200 and resp.json() == {"status": "SUCCESS"}
        assert (await c.post("/dapr/events/other.topic", json={})).status_code == 404
    await http.state.backends.events.drain()
    assert [e.source for e in seen] == ["dapr"]


async def test_dapr_publisher_relays_events_when_a_sidecar_is_present(http):
    from ahdt.services.dapr import DaprPublisher
    from atra.contracts import EventEnvelope

    calls = []

    def handle(request):
        calls.append(request)
        return httpx.Response(204)

    sidecar = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    relay = DaprPublisher(http.state.backends, port="3500", client=sidecar)
    event = EventEnvelope(event_id="e2", event_type="model.drift_detected", source="ahdt.x",
                          wall_time=T0, trace_id="t2", payload={})
    await relay.relay(event)
    await relay.relay(event)
    assert len(calls) == 1
    assert calls[0].url.path == "/v1.0/publish/atra-pubsub/model.drift_detected"


async def test_model_stages_follow_the_roles(http):
    cso = bearer(token(http, Role.CLINICAL_SAFETY_OFFICER))
    admin = bearer(token(http, Role.ADMINISTRATOR))
    model = "ahdt.cardiovascular.baroreflex_regulation"
    async with client(http) as c:
        listed = (await c.get("/v1/models", headers=cso)).json()
        version = next(m["version"] for m in listed if m["model_id"] == model)
        assert all(m["stage"] == "None" for m in listed if m["model_id"] == model)
        base = f"/v1/models/{model}/versions/{version}/stage"
        assert (await c.post(base, json={"stage": "Production"}, headers=cso)).status_code == 409
        assert (await c.post(base, json={"stage": "Staging"}, headers=admin)).status_code == 200
        assert (await c.post(base, json={"stage": "Production"}, headers=admin)).status_code == 403
        assert (await c.post(base, json={"stage": "Production"}, headers=cso)).status_code == 200
        assert (await c.post(base, json={"stage": "Archived"}, headers=cso)).status_code == 200
        back = await c.post(f"/v1/models/{model}/rollback", headers=cso)
        assert back.status_code == 200 and back.json()["version"] == version
        assert (await c.post(f"/v1/models/{model}/rollback", headers=admin)).status_code == 403
    actions = [r.action for r in http.state.audit]
    assert "model.stage" in actions and "model.rollback" in actions


async def test_reidentification_is_audited_and_restricted(http):
    pipe = await http.state.runtime.pipeline()
    hdt = await pipe.pseudonyms.hdt_id("urn:test", "NIN-1")
    admin = bearer(token(http, Role.ADMINISTRATOR), **{"X-Purpose-Of-Use": "operations"})
    mo = bearer(token(http, Role.MEDICAL_OFFICER))
    async with client(http) as c:
        ok = await c.post("/v1/identity/reidentify", json={"hdt_id": hdt}, headers=admin)
        assert ok.status_code == 200
        assert ok.json()["identifiers"] == [{"system": "urn:test", "value": "NIN-1"}]
        assert (await c.post("/v1/identity/reidentify", json={"hdt_id": hdt},
                             headers=mo)).status_code == 403
        wrong = bearer(token(http, Role.ADMINISTRATOR))
        assert (await c.post("/v1/identity/reidentify", json={"hdt_id": hdt},
                             headers=wrong)).status_code == 403
    outcomes = [r.outcome for r in http.state.audit if r.action == "identity.reidentify"]
    assert outcomes == ["ok", "denied", "denied"]
