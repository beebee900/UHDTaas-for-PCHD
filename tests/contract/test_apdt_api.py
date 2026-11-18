import json
from datetime import UTC, datetime

import httpx
import pytest
from starlette.testclient import TestClient

from apdt.app import build_app
from apdt.services.inputs import to_resources
from atra import contracts as c
from atra.consent import to_fhir
from atra.contracts import Role
from atra.demo_users import LOGINS_NAME, UserStore, write
from atra.personas import BY_KEY
from evaluation.models.apdt.scenarios import BY_SCENARIO

AO = BY_KEY["ao"]
EP = f"ep-{datetime.now(UTC).year}-000001"


@pytest.fixture
def apdt(settings, backends):
    app = build_app(settings, backends=backends("apdt"))
    ep = app.state.episodes.create("fac-a", c.EpisodeCreate(
        hdt_id=AO.hdt_id, reason="Fever for two days"), "medical_officer.fac-a")
    assert ep.episode_id == EP
    scenario = BY_SCENARIO["ao"]
    for resource in to_resources(scenario.patient, scenario.observations):
        app.state.episodes.add_resource("fac-a", EP, resource)
    return app


def tok(app, role, tenant="fac-a", **kw):
    return app.state.backends.issuer.issue(f"{role}.{tenant}", Role(role), tenant_id=tenant, **kw)


def client(app):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://apdt")


def h(token):
    return {"Authorization": f"Bearer {token}"}


async def test_clinician_routes_return_contract_bodies(apdt, settings):
    mo = h(tok(apdt, "medical_officer"))
    base = "/v1/t/fac-a"
    async with client(apdt) as cl:
        r = await cl.post(f"{base}/episodes", headers=mo,
                          json={"hdt_id": AO.hdt_id, "reason": "Fever"})
        assert r.status_code == 201
        new_ep = c.EpisodeView.model_validate(r.json()).episode.episode_id
        c.EpisodeView.model_validate((await cl.get(f"{base}/episodes/{EP}", headers=mo)).json())
        obs = {"resourceType": "Observation", "status": "final",
               "code": {"coding": [{"system": "http://loinc.org", "code": "8310-5"}]}}
        assert (await cl.post(f"{base}/episodes/{EP}/resources", headers=mo,
                              json=obs)).status_code == 201
        r = await cl.post(f"{base}/episodes/{EP}/goals/diagnosis", headers=mo)
        run_id = c.RunStarted.model_validate(r.json()).run_id
        run = c.RunStatus.model_validate((await cl.get(f"{base}/runs/{run_id}", headers=mo)).json())
        assert run.status == "waiting_for_human" and run.interrupt.kind == "accept_diagnosis"
        decision = {"decision_id": "d-1",
                    "recommendation_id": run.interrupt.payload["recommendation_id"],
                    "decided_by": {"id": "medical_officer.fac-a", "role": "medical_officer"},
                    "decision": "accept", "signature": "stub"}
        r = await cl.post(f"{base}/runs/{run_id}/resume", headers=mo, json=decision)
        assert c.RunStatus.model_validate(r.json()).status == "done"
        recs = (await cl.get(f"{base}/episodes/{EP}/recommendations", headers=mo)).json()
        bundle_id = c.Recommendation.model_validate(recs[0]).bundle_id
        bundle = c.ExplanationBundle.model_validate(
            (await cl.get(f"{base}/bundles/{bundle_id}", headers=mo)).json())
        assert bundle.missing_parts() == ["simulation_trace"]
        c.UnifiedView.model_validate(
            (await cl.get(f"{base}/episodes/{EP}/unified-view", headers=mo)).json())
        panel = c.AHDTPanel.model_validate(
            (await cl.get(f"{base}/episodes/{EP}/ahdt-panel", headers=mo)).json())
        assert len(panel.tiles) == 17
        c.Worklist.model_validate(
            (await cl.get(f"{base}/worklists/medical_officer", headers=mo)).json())
        r = await cl.post(f"{base}/alerts/al-1/ack", headers=mo, json={"by": "rn-1"})
        c.AlertAckResult.model_validate(r.json())
        r = await cl.post(f"{base}/referrals", headers=mo,
                          json={"episode_id": EP, "to_tenant": "fac-b", "reason": "CT scan"})
        referral = c.ReferralResult.model_validate(r.json())
        bundle = json.loads((settings.var_dir / referral.bundle_ref).read_text())
        request, *shared = [e["resource"] for e in bundle["entry"]]
        assert request["id"] == referral.referral_id
        assert request["performer"][0]["identifier"]["value"] == "fac-b"
        assert len(request["supportingInfo"]) == len(shared) > 0
        r = await cl.post(f"{base}/episodes/{new_ep}/close", headers=mo, json={"outcome": "cured"})
        assert c.Episode.model_validate(r.json()).status == "closed"
        audit = (await cl.get(f"{base}/audit", headers=mo)).json()
        assert all(a["tenant_id"] == "fac-a" for a in audit) and len(audit) > 10


async def test_route_policy(apdt):
    async with client(apdt) as cl:
        other = h(tok(apdt, "medical_officer", "fac-b"))
        r = await cl.get(f"/v1/t/fac-a/episodes/{EP}", headers=other)
        assert r.status_code == 403
        nurse = h(tok(apdt, "nurse"))
        r = await cl.post(f"/v1/t/fac-a/episodes/{EP}/goals/diagnosis", headers=nurse)
        assert r.status_code == 403
        mo = h(tok(apdt, "medical_officer"))
        r = await cl.post(f"/v1/t/fac-a/episodes/{EP}/goals/treatment", headers=mo)
        run_id = r.json()["run_id"]
        pharmacist = h(tok(apdt, "pharmacist"))
        decision = {"decision_id": "d-2", "recommendation_id": "rec-stub",
                    "decided_by": {"id": "pharmacist.fac-a", "role": "pharmacist"},
                    "decision": "sign", "signature": "stub"}
        r = await cl.post(f"/v1/t/fac-a/runs/{run_id}/resume", headers=pharmacist, json=decision)
        assert r.status_code == 403 and "medical_officer" in r.json()["detail"]
        r = await cl.get(f"/v1/t/fac-c/episodes/{EP}", headers=mo)
        assert r.status_code == 422
        assert (await cl.get("/v1/t/fac-a/worklists/nurse", headers=nurse)).status_code == 200
        r = await cl.get("/v1/t/fac-a/worklists/medical_officer", headers=nurse)
        assert r.status_code == 403


async def test_patient_consent_and_messages(apdt):
    pt = h(apdt.state.backends.issuer.issue("patient.ao", Role.PATIENT, tenant_id="fac-a",
                                            hdt_id=AO.hdt_id))
    base = f"/v1/t/fac-a/patients/{AO.hdt_id}"
    async with client(apdt) as cl:
        consent = to_fhir(AO.hdt_id, ["care"], ["ahdt.data.genome"], consent_id="cons-1")
        r = await cl.put(f"{base}/consent", headers=pt, json=consent)
        assert r.status_code == 200 and r.json()["refused_tools"] == ["ahdt.data.genome"]
        assert apdt.state.consents.get(AO.hdt_id).refused_tools == {"ahdt.data.genome"}
        r = await cl.post(f"{base}/messages", headers=pt,
                          json={"text": "Mo ni iba", "language": "yo"})
        assert c.PatientReply.model_validate(r.json()).language == "yo"
        other = f"/v1/t/fac-a/patients/{BY_KEY['cn'].hdt_id}/messages"
        r = await cl.post(other, headers=pt, json={"text": "x", "language": "en"})
        assert r.status_code == 403


async def test_standards_endpoints(apdt):
    async with client(apdt) as cl:
        services = (await cl.get("/cds-services")).json()["services"]
        assert {s["hook"] for s in services} == {"patient-view", "order-select", "order-sign"}
        r = await cl.post("/cds-services/apdt-patient-view", json={"hook": "patient-view"})
        assert r.json()["cards"]
        smart = (await cl.get("/smart/.well-known/smart-configuration")).json()
        assert "launch-ehr" in smart["capabilities"]
        assert (await cl.get("/.well-known/jwks.json")).json()["keys"]


async def test_local_login(apdt, settings, tmp_path):
    env = write(settings, env_file=tmp_path / "demo.env")
    passwords = dict(line.split("=", 1) for line in env.read_text().splitlines()[1:])
    password = passwords["DEMO_USER_MEDICAL_OFFICER_FAC_A"]
    logins = (tmp_path / LOGINS_NAME).read_text().splitlines()
    assert ["medical_officer.fac-a", "medical_officer", password] in [r.split() for r in logins]
    assert UserStore(settings.var_dir / "keys" / "demo-users.json").check(
        "medical_officer.fac-a", password)
    async with client(apdt) as cl:
        r = await cl.post("/auth/token", json={"username": "medical_officer.fac-a",
                                               "password": password})
        assert r.status_code == 200 and r.json()["tenant_id"] == "fac-a"
        r2 = await cl.get(f"/v1/t/fac-a/episodes/{EP}", headers=h(r.json()["access_token"]))
        assert r2.status_code == 200
        bad = await cl.post("/auth/token", json={"username": "medical_officer.fac-a",
                                                 "password": "wrong"})
        assert bad.status_code == 401


def test_event_stream(apdt):
    mo = tok(apdt, "medical_officer")
    with TestClient(apdt) as tc, tc.websocket_connect(
            f"/v1/t/fac-a/stream?access_token={mo}") as ws:
        tc.post("/v1/t/fac-a/episodes", headers=h(mo), json={"hdt_id": AO.hdt_id, "reason": "x"})
        event = c.EventEnvelope.model_validate_json(ws.receive_text())
        assert event.event_type == "episode.opened" and event.tenant_id == "fac-a"


async def test_apdt_mcp_tools(apdt, live):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from mcp.shared._httpx_utils import create_mcp_http_client

    mo = tok(apdt, "medical_officer")
    with live(apdt) as server:
        http = create_mcp_http_client(headers=h(mo))
        url = f"{server.url}/mcp/apdt/"
        async with http, streamable_http_client(url, http_client=http) as (rd, wr), \
                ClientSession(rd, wr) as session:
            await session.initialize()
            names = {t.name for t in (await session.list_tools()).tools}
            assert names == set(c.APDT_TOOL_ARGS)
            res = await session.call_tool("apdt.diagnosis.differential",
                                          {"tenant_id": "fac-a", "episode_id": EP})
            assert not res.is_error
            c.DifferentialData.model_validate(
                {k: v for k, v in res.structured_content.items() if k != "_meta"})
            res = await session.call_tool("apdt.consent.get",
                                          {"tenant_id": "fac-b", "hdt_id": AO.hdt_id})
            assert res.is_error and res.structured_content["error"]["status"] == 403
