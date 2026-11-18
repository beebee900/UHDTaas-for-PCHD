"""The APDT agent graphs: the diagnosis and treatment orchestrators over the run API."""
# ruff: noqa: F401, F811

import pytest

from apdt.agents.clinical import DifferentialDiagnosisAgent
from apdt.agents.diagnosis import ORDER
from apdt.agents.treatment import MAX_SIMULATED
from atra import contracts as c
from atra.telemetry import span_store
from tests.contract.test_apdt_api import AO, EP, apdt, client, h, tok
from tests.contract.test_apdt_clinical import (
    BASE,
    decision,
    http,
    make_twins,
    start,
)

BASE_A = BASE.format(tenant="fac-a")


async def begin(cl, app, goal="diagnosis"):
    mo = h(tok(app, "medical_officer"))
    r = await cl.post(f"{BASE_A}/episodes/{EP}/goals/{goal}", headers=mo)
    run_id = c.RunStarted.model_validate(r.json()).run_id
    run = c.RunStatus.model_validate((await cl.get(f"{BASE_A}/runs/{run_id}",
                                                   headers=mo)).json())
    return mo, run_id, run


def nodes(run: c.RunStatus) -> list[str]:
    return [s["node"] for s in run.result["steps"]]


def node_spans() -> list[str]:
    spans = [s for s in span_store().get_finished_spans() if s.name.startswith("apdt.node.")]
    return [s.name.removeprefix("apdt.node.") for s in sorted(spans, key=lambda s: s.start_time)]


async def test_diagnosis_graph_stops_at_the_interrupt_with_the_agent_steps(apdt):
    async with client(apdt) as cl:
        _, _, run = await begin(cl, apdt)
    assert run.status == "waiting_for_human" and run.interrupt.kind == "accept_diagnosis"
    assert run.interrupt.payload["recommendation_id"].startswith("rec-")
    assert nodes(run) == list(ORDER[:5])
    steps = {s["node"]: s for s in run.result["steps"]}
    assert steps["rank_differential"]["agent"] == "differential-diagnosis-agent"
    assert steps["rank_differential"]["tool_calls"][0]["tool"] == "apdt.models.differential"
    assert steps["assemble_evidence"]["agent"] == "evidence-assembly-agent"
    assert "ahdt.data.observations" in {t["tool"] for t in steps["assemble_evidence"]["tool_calls"]}
    assert steps["suggest_tests"]["agent"] == "investigation-agent"
    assert run.interrupt.payload["test_recommendation_id"].startswith("rec-")


@pytest.mark.parametrize(("kind", "status", "extra"), [
    ("accept", "accepted", {}),
    ("edit", "edited", {"override_reason": "Typhoid not excluded",
                        "edited_payload": {"note": "confirm with blood culture"}}),
    ("reject", "overridden", {"override_reason": "Alternative cause"})])
async def test_diagnosis_graph_resumes_on_each_decision(apdt, kind, status, extra):
    async with client(apdt) as cl:
        mo, run_id, run = await begin(cl, apdt)
        rec_id = run.interrupt.payload["recommendation_id"]
        r = await cl.post(f"{BASE_A}/runs/{run_id}/resume", headers=mo,
                          json=decision(rec_id, kind, **extra))
        assert r.status_code == 200
        done = c.RunStatus.model_validate(r.json())
    assert done.status == "done" and done.interrupt is None
    assert done.result["status"] == status and done.result["decision"] == kind
    assert nodes(done)[-1] == "record_working_diagnosis"
    assert apdt.state.episodes.recommendation(rec_id).status == status


async def test_diagnosis_spans_follow_msc1(apdt):
    span_store().clear()
    async with client(apdt) as cl:
        mo, run_id, run = await begin(cl, apdt)
        assert node_spans() == list(ORDER[:6])
        rec_id = run.interrupt.payload["recommendation_id"]
        await cl.post(f"{BASE_A}/runs/{run_id}/resume", headers=mo,
                      json=decision(rec_id, "accept"))
    assert node_spans() == [*ORDER[:6], "accept_diagnosis", "record_working_diagnosis"]
    tools = {s.name for s in span_store().get_finished_spans()
             if s.name.startswith("apdt.tool.")}
    assert "apdt.tool.apdt.models.differential" in tools


async def test_an_agent_sign_attempt_inside_the_graph_is_refused_and_audited(apdt):
    class Rogue(DifferentialDiagnosisAgent):
        async def run(self, ep, ctx, goal_id):
            out = await super().run(ep, ctx, goal_id)
            self.kit(ep, ctx).attempt("sign", out.data["recommendation_id"])
            return out

    runs = apdt.state.run_service
    runs.agents.differential = Rogue(runs.agents.guard, runs.store, runs.recommender)
    async with client(apdt) as cl:
        _, _, run = await begin(cl, apdt)
    assert run.status == "failed" and run.result["denied"]
    [rec] = apdt.state.audit.query(action="agent.sign", outcome="denied")
    assert rec.actor.id == "differential-diagnosis-agent" and rec.target.startswith("rec-")
    assert all(r.status == "proposed" for r in apdt.state.episodes.recommendations[EP])


async def test_a_run_without_age_and_sex_fails_at_the_differential(apdt):
    ep = apdt.state.episodes.create("fac-a", c.EpisodeCreate(hdt_id=AO.hdt_id, reason="Fever"),
                                    "medical_officer.fac-a")
    async with client(apdt) as cl:
        mo = h(tok(apdt, "medical_officer"))
        r = await cl.post(f"{BASE_A}/episodes/{ep.episode_id}/goals/diagnosis", headers=mo)
        run = (await cl.get(f"{BASE_A}/runs/{r.json()['run_id']}", headers=mo)).json()
    assert run["status"] == "failed" and "age_years" in run["result"]["error"]
    assert [s["node"] for s in run["result"]["steps"]][-1] == "rank_differential"


async def test_treatment_graph_reaches_both_interrupts_in_order(make_twins):
    twins = await make_twins("ao")
    async with http(twins.apdt) as cl:
        run_id, run = await start(cl, twins, "ao", "treatment")
        rec_id = run.interrupt.payload["recommendation_id"]
        assert run.interrupt.kind == "sign_prescription"
        assert run.interrupt.required_role == c.Role.MEDICAL_OFFICER
        assert nodes(run) == ["enumerate_options", "check_options", "simulate_each", "explain"]
        options = run.interrupt.payload["options"]
        simulated = [o for o in options if o["simulation"] or o["simulation_error"]]
        assert len(simulated) == min(len(options), MAX_SIMULATED)
        assert options[0]["simulation"] and not options[0]["simulation_error"]
        resume = f"{BASE_A}/runs/{run_id}/resume"
        pharmacist = h(tok(twins.apdt, "pharmacist", "fac-a"))
        early = await cl.post(resume, headers=pharmacist, json=decision(
            rec_id, "verify", "pharmacist.fac-a", "pharmacist"))
        assert early.status_code == 403
        r = await cl.post(resume, headers=twins.mo(), json=decision(rec_id, "sign"))
        second = c.RunStatus.model_validate(r.json())
        assert second.status == "waiting_for_human"
        assert second.interrupt.kind == "verify_prescription"
        assert second.interrupt.required_role == c.Role.PHARMACIST
        r = await cl.post(resume, headers=pharmacist, json=decision(
            rec_id, "verify", "pharmacist.fac-a", "pharmacist"))
        done = c.RunStatus.model_validate(r.json())
    assert done.status == "done" and done.result["status"] == "signed"
    assert done.result["signed_by"] == "medical_officer.fac-a"
    assert nodes(done)[-2:] == ["record_signature", "record_verification"]


async def test_a_refused_simulation_is_an_error_in_the_result(apdt):
    async with client(apdt) as cl:
        _, _, run = await begin(cl, apdt, "treatment")
    assert run.status == "waiting_for_human" and run.interrupt.kind == "sign_prescription"
    sims = next(s for s in run.result["steps"] if s["node"] == "simulate_each")["output"]
    assert sims["simulations"] and all(s["error"] and s["simulation"] is None
                                       for s in sims["simulations"])
