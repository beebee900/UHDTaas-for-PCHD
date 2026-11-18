"""The APDT's clinical path: the reasoner, bundles, the live AHDT through the gateway, goal
runs and worklists, for the six demo personas."""

import httpx
import pytest

from ahdt.app import build_app as build_ahdt
from apdt.app import build_app
from apdt.demo_seed import seed
from apdt.models.context import kb
from atra import contracts as c
from atra.contracts import Role
from atra.personas import BY_HDT, BY_KEY, PERSONAS
from evaluation.models.apdt.scenarios import BY_SCENARIO

BASE = "/v1/t/{tenant}"


def tok(app, role, tenant="fac-a", **kw):
    return app.state.backends.issuer.issue(f"{role}.{tenant}", Role(role), tenant_id=tenant, **kw)


def h(token):
    return {"Authorization": f"Bearer {token}"}


def http(app, name="apdt"):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=f"http://{name}")


class Twins:
    """An APDT wired to a live AHDT, with every persona seeded."""

    def __init__(self, apdt, ahdt, summary):
        self.apdt, self.ahdt, self.summary = apdt, ahdt, summary

    def mo(self, tenant="fac-a"):
        return h(tok(self.apdt, "medical_officer", tenant))

    def episode(self, key):
        return next(s["episode_id"] for s in self.summary if s["persona"] == key)


@pytest.fixture
async def make_twins(settings, backends):
    """Build an APDT wired to a live AHDT and seed the given personas."""
    clients = []

    async def build(*keys):
        ahdt = build_ahdt(settings, backends=backends("ahdt"), local_llm=False)
        ahdt_backends = ahdt.state.backends
        apdt_backends = backends("apdt")
        apdt_backends.__dict__["issuer"] = ahdt_backends.issuer
        ahdt_client = http(ahdt, "ahdt")
        clients.append(ahdt_client)
        apdt = build_app(settings, backends=apdt_backends, ahdt_client=ahdt_client)
        async with http(apdt) as client:
            summary = await seed(client, ahdt_client, ahdt_backends.issuer,
                                 [BY_KEY[k] for k in keys])
        return Twins(apdt, ahdt, summary)

    yield build
    for client in clients:
        await client.aclose()


async def recommendations(twins, key):
    tenant = BY_KEY[key].tenant_id
    async with http(twins.apdt) as cl:
        r = await cl.get(f"{BASE.format(tenant=tenant)}/episodes/{twins.episode(key)}"
                         "/recommendations", headers=twins.mo(tenant))
    assert r.status_code == 200, r.text
    return [c.Recommendation.model_validate(x) for x in r.json()]


async def bundle_of(twins, rec, audience="medical_officer", tenant="fac-a"):
    async with http(twins.apdt) as cl:
        r = await cl.get(f"{BASE.format(tenant=tenant)}/bundles/{rec.bundle_id}",
                         params={"audience": audience}, headers=twins.mo(tenant))
    assert r.status_code == 200, r.text
    return c.ExplanationBundle.model_validate(r.json())


async def check_persona(twins, key):
    scenario = BY_SCENARIO[key]
    tenant = BY_KEY[key].tenant_id
    recs = await recommendations(twins, key)
    by_kind = {r.kind: r for r in recs}
    assert {"diagnosis", "treatment", "care"} <= set(by_kind)
    assert by_kind["diagnosis"].payload["condition"] == scenario.expected_top
    assert by_kind["treatment"].payload["option_id"] == scenario.expected_first_option
    assert all(r.status == "proposed" and r.hdt_id == BY_KEY[key].hdt_id for r in recs)
    for rec in recs:
        bundle = await bundle_of(twins, rec, tenant=tenant)
        assert bundle.missing_parts() == [], (key, rec.kind)
        assert bundle.recommendation_id == rec.recommendation_id
        assert bundle.model_versions
        for cite in bundle.citations:
            assert cite.kb_entry_id in kb() and cite.section and cite.source_title
        assert bundle.simulation_trace and bundle.simulation_trace.fork_id
        assert bundle.patient_summary.text


async def test_six_personas_have_complete_bundles_and_full_worklists(make_twins):
    twins = await make_twins(*[p.key for p in PERSONAS])
    for p in PERSONAS:
        await check_persona(twins, p.key)
    async with http(twins.apdt) as cl:
        mo = c.Worklist.model_validate((await cl.get(
            f"{BASE.format(tenant='fac-a')}/worklists/medical_officer",
            headers=twins.mo())).json())
        ph = c.Worklist.model_validate((await cl.get(
            f"{BASE.format(tenant='fac-b')}/worklists/pharmacist",
            headers=h(tok(twins.apdt, "pharmacist", "fac-b")))).json())
    fac_a = {p.hdt_id for p in PERSONAS if p.tenant_id == "fac-a"}
    assert {i.hdt_id for i in mo.items} == fac_a
    assert {i.hdt_id for i in ph.items} == {BY_KEY["de"].hdt_id, BY_KEY["gh"].hdt_id}
    assert ph.items[0].priority == 1 and BY_HDT[ph.items[0].hdt_id].key == "gh"


async def test_treatment_safety_issue_reaches_the_recommendation(make_twins):
    twins = await make_twins("gh")
    treatment = next(r for r in await recommendations(twins, "gh") if r.kind == "treatment")
    ids = {i["ix_id"] for i in treatment.payload["issues"]}
    assert "ix.dolutegravir.rifampicin" in ids and treatment.payload["blocks_signing"]
    assert all(i["detected_issue"]["resourceType"] == "DetectedIssue"
               for i in treatment.payload["issues"])
    bundle = await bundle_of(twins, treatment, "pharmacist", tenant="fac-b")
    assert bundle.citations and not bundle.counterfactuals


async def test_patient_view_holds_the_summary_only(make_twins):
    twins = await make_twins("ao")
    rec = (await recommendations(twins, "ao"))[0]
    patient = h(tok(twins.apdt, "patient", hdt_id=BY_KEY["ao"].hdt_id))
    async with http(twins.apdt) as cl:
        r = await cl.get(f"{BASE.format(tenant='fac-a')}/bundles/{rec.bundle_id}",
                         params={"audience": "medical_officer"}, headers=patient)
    view = c.ExplanationBundle.model_validate(r.json())
    assert view.patient_summary.text and not view.evidence_for and not view.citations


async def test_unified_view_and_panel_come_from_both_twins(make_twins):
    twins = await make_twins("ao")
    eid = twins.episode("ao")
    async with http(twins.apdt) as cl:
        view = c.UnifiedView.model_validate((await cl.get(
            f"{BASE.format(tenant='fac-a')}/episodes/{eid}/unified-view",
            headers=twins.mo())).json())
        panel = c.AHDTPanel.model_validate((await cl.get(
            f"{BASE.format(tenant='fac-a')}/episodes/{eid}/ahdt-panel",
            headers=twins.mo())).json())
    assert not view.degraded and not view.missing_evidence
    assert {i.source for i in view.items} == {"apdt", "ahdt"}
    assert any(i.source == "ahdt" and i.label == "Temperature" for i in view.items)
    assert any(i.source == "apdt" and i.kind == "test" for i in view.items)
    assert len(panel.tiles) == 17 and not panel.degraded
    assert panel.vitals["temperature"].source == "ahdt"
    assert any(t.status != "unavailable" for t in panel.tiles)


async def start(cl, twins, key, goal):
    tenant = BY_KEY[key].tenant_id
    r = await cl.post(f"{BASE.format(tenant=tenant)}/episodes/{twins.episode(key)}/goals/{goal}",
                      headers=twins.mo(tenant))
    run_id = c.RunStarted.model_validate(r.json()).run_id
    run = c.RunStatus.model_validate((await cl.get(
        f"{BASE.format(tenant=tenant)}/runs/{run_id}", headers=twins.mo(tenant))).json())
    return run_id, run


def decision(rec_id, kind, who="medical_officer.fac-a", role="medical_officer", **kw):
    return {"decision_id": f"d-{kind}", "recommendation_id": rec_id,
            "decided_by": {"id": who, "role": role}, "decision": kind, "signature": "sig", **kw}


async def test_diagnosis_run_decisions_change_the_status(make_twins):
    twins = await make_twins("ao")
    async with http(twins.apdt) as cl:
        base = BASE.format(tenant="fac-a")
        run_id, run = await start(cl, twins, "ao", "diagnosis")
        rec_id = run.interrupt.payload["recommendation_id"]
        assert run.status == "waiting_for_human"
        assert run.interrupt.required_role == Role.MEDICAL_OFFICER
        assert run.interrupt.payload["bundle_id"].startswith("bun-")
        resume = f"{base}/runs/{run_id}/resume"
        r = await cl.post(resume, headers=twins.mo(), json=decision(rec_id, "reject"))
        assert r.status_code == 422
        r = await cl.post(resume, headers=twins.mo(), json=decision("rec-other", "accept"))
        assert r.status_code == 422
        edit = decision(rec_id, "edit", override_reason="Typhoid not excluded",
                        edited_payload={"note": "confirm with blood culture"})
        r = await cl.post(resume, headers=twins.mo(), json=edit)
        assert r.status_code == 200 and r.json()["result"]["status"] == "edited"
        recs = await recommendations(twins, "ao")
        edited = next(x for x in recs if x.recommendation_id == rec_id)
        assert edited.status == "edited" and edited.payload["note"] == "confirm with blood culture"
        wl = c.Worklist.model_validate((await cl.get(
            f"{base}/worklists/medical_officer", headers=twins.mo())).json())
        assert f"wl-{rec_id}" not in {i.item_id for i in wl.items}


async def test_a_blocked_treatment_is_edited_then_goes_to_the_pharmacist(make_twins):
    twins = await make_twins("gh")
    async with http(twins.apdt) as cl:
        base = BASE.format(tenant="fac-b")
        run_id, run = await start(cl, twins, "gh", "treatment")
        rec_id = run.interrupt.payload["recommendation_id"]
        assert run.interrupt.kind == "sign_prescription"
        assert run.interrupt.payload["blocks_signing"]
        resume = f"{base}/runs/{run_id}/resume"
        pharmacist = h(tok(twins.apdt, "pharmacist", "fac-b"))
        blocked = await cl.post(resume, headers=twins.mo("fac-b"), json=decision(
            rec_id, "sign", "medical_officer.fac-b"))
        assert blocked.status_code == 422 and "blocks signing" in blocked.json()["detail"]
        r = await cl.post(resume, headers=twins.mo("fac-b"), json=decision(
            rec_id, "edit", "medical_officer.fac-b", override_reason="Avoid the interaction",
            edited_payload={"note": "choose an option without the interaction"}))
        assert r.json()["interrupt"]["kind"] == "verify_prescription"
        wrong = await cl.post(resume, headers=twins.mo("fac-b"), json=decision(
            rec_id, "verify", "medical_officer.fac-b"))
        assert wrong.status_code == 403
        r = await cl.post(resume, headers=pharmacist, json=decision(
            rec_id, "reject", "pharmacist.fac-b", "pharmacist", override_reason="Use raltegravir"))
        assert r.status_code == 200 and r.json()["result"]["status"] == "overridden"


async def test_agent_sign_off_is_refused_and_audited(make_twins):
    twins = await make_twins("ao")
    async with http(twins.apdt) as cl:
        base = BASE.format(tenant="fac-a")
        run_id, run = await start(cl, twins, "ao", "diagnosis")
        rec_id = run.interrupt.payload["recommendation_id"]
        resume = f"{base}/runs/{run_id}/resume"
        agent = decision(rec_id, "sign", "differential-diagnosis-agent", "medical_officer")
        r = await cl.post(resume, headers=twins.mo(), json=agent)
        assert r.status_code == 403
        service = h(twins.apdt.state.backends.issuer.issue_service("agent-svc"))
        r = await cl.post(resume, headers={**service, "X-Actor-Role": "medical_officer",
                                           "X-Actor-Id": "medical_officer.fac-a"},
                          json=decision(rec_id, "sign"))
        assert r.status_code == 403
        audit = (await cl.get(f"{base}/audit", headers=twins.mo())).json()
        refused = [a for a in audit if a["action"] == "decision.sign" and a["outcome"] == "denied"]
        assert len(refused) == 2 and all(a["target"] == rec_id for a in refused)
        recs = await recommendations(twins, "ao")
        assert next(x for x in recs if x.recommendation_id == rec_id).status == "proposed"
        r = await cl.post(resume, headers=twins.mo(), json=decision(rec_id, "sign"))
        assert r.status_code == 200 and r.json()["result"]["status"] == "signed"


async def test_an_accepted_diagnosis_is_written_back_to_the_ahdt(make_twins):
    twins = await make_twins("ao")
    ao = BY_KEY["ao"].hdt_id
    reader = h(tok(twins.ahdt, "medical_officer"))
    async with http(twins.apdt) as cl, http(twins.ahdt, "ahdt") as ahdt:
        async def conditions():
            r = await ahdt.get("/v1/fhir/Condition", params={"subject": ao}, headers=reader)
            assert r.status_code == 200, r.text
            return {e["resource"]["id"]: e["resource"] for e in r.json()["entry"]}

        before = await conditions()
        run_id, run = await start(cl, twins, "ao", "diagnosis")
        rec_id = run.interrupt.payload["recommendation_id"]
        r = await cl.post(f"{BASE.format(tenant='fac-a')}/runs/{run_id}/resume",
                          headers=twins.mo(), json=decision(rec_id, "accept"))
        assert r.status_code == 200 and r.json()["result"]["status"] == "accepted"
        after = await conditions()
        refused = await ahdt.post(f"/v1/persons/{ao}/findings", content=b"{}", headers=reader)
    [new] = [after[k] for k in after.keys() - before.keys()]
    assert new["code"]["coding"][0] == {"system": "http://snomed.info/sct", "code": "62676009",
                                        "display": "Plasmodium falciparum malaria"}
    assert new["verificationStatus"]["coding"][0]["code"] == "provisional"
    assert new["subject"] == {"reference": f"Patient/{ao}"}
    assert refused.status_code == 403
    audit = [a for a in twins.apdt.state.audit if a.action == "ahdt.write_back"]
    assert [(a.outcome, a.target) for a in audit] == [("ok", rec_id)]


async def test_ahdt_outage_degrades_and_names_the_missing_evidence(settings, backends):
    def down(request):
        raise httpx.ConnectError("AHDT is down", request=request)

    apdt = build_app(settings, backends=backends("apdt"),
                     ahdt_client=httpx.AsyncClient(transport=httpx.MockTransport(down)))
    scenario = BY_SCENARIO["ao"]
    from apdt.services.inputs import to_resources

    ep = apdt.state.episodes.create("fac-a", c.EpisodeCreate(
        hdt_id=BY_KEY["ao"].hdt_id, reason="Fever"), "medical_officer.fac-a")
    for resource in to_resources(scenario.patient, scenario.observations):
        apdt.state.episodes.add_resource("fac-a", ep.episode_id, resource)
    mo = h(tok(apdt, "medical_officer"))
    base = f"{BASE.format(tenant='fac-a')}/episodes/{ep.episode_id}"
    async with http(apdt) as cl:
        recs = [c.Recommendation.model_validate(x)
                for x in (await cl.get(f"{base}/recommendations", headers=mo)).json()]
        view = c.UnifiedView.model_validate((await cl.get(f"{base}/unified-view",
                                                          headers=mo)).json())
        panel = c.AHDTPanel.model_validate((await cl.get(f"{base}/ahdt-panel",
                                                         headers=mo)).json())
        bundle = c.ExplanationBundle.model_validate((await cl.get(
            f"{BASE.format(tenant='fac-a')}/bundles/{recs[0].bundle_id}", headers=mo)).json())
    assert view.degraded and view.items and {i.source for i in view.items} == {"apdt"}
    assert any(m.startswith("ahdt.data.observations") for m in view.missing_evidence)
    assert any(m.startswith("ahdt.data.medications") for m in view.missing_evidence)
    assert panel.degraded and all(t.status == "unavailable" for t in panel.tiles)
    assert bundle.missing_parts() == ["simulation_trace"]
