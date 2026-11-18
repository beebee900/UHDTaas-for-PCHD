import httpx
import pytest

from ahdt.agents.guard import ActionDenied
from atra.connectors import DTKind
from atra.contracts import Role
from tests.contract.fixtures import HDT
from tests.unit.ahdt.agents.conftest import NOW, token

MSK_EXERCISE = {"plan_id": "msk-exercise", "twin": "musculoskeletal",
                "action": "Start a graded exercise plan", "risk": 0.1,
                "risk_to": {"cardiovascular": 0.35}}
CV_REST = {"plan_id": "cv-monitor", "twin": "cardiovascular",
           "action": "Rest and monitor blood pressure", "risk": 0.05,
           "risk_to": {"musculoskeletal": 0.1}}


def test_arbitration_chooses_the_safe_plan_over_an_exercise_plan(hub):
    decision = hub.conductor.arbitrate([MSK_EXERCISE, CV_REST])
    assert decision.chosen == "cv-monitor"
    assert decision.excluded == [{"plan_id": "msk-exercise",
                                  "reason": "risk to higher-priority twin: cardiovascular"}]


def test_priority_decides_when_the_exercise_plan_is_not_unsafe(hub):
    mild = {**MSK_EXERCISE, "risk_to": {"cardiovascular": 0.1}}
    decision = hub.conductor.arbitrate([mild, CV_REST])
    assert decision.chosen == "cv-monitor" and decision.rule == "fixed clinical priority"
    assert decision.ranking == ["cv-monitor", "msk-exercise"]


def test_a_tie_takes_the_lower_risk_plan_and_notes_the_deferred_search(hub):
    a = {"plan_id": "a", "twin": "renal_urinary", "action": "x", "risk": 0.2}
    b = {"plan_id": "b", "twin": "endocrine", "action": "y", "risk": 0.1}
    decision = hub.conductor.arbitrate([a, b])
    assert decision.chosen == "b" and decision.rule == "lower risk"
    assert "NSGA-II" in decision.notes[0]


def test_no_safe_plan_chooses_nothing(hub):
    only = {**MSK_EXERCISE}
    decision = hub.conductor.arbitrate([only])
    assert decision.chosen is None and decision.rule == "no safe plan"


async def test_the_conductor_decomposes_a_person_goal_with_cited_thresholds(hub, ctx, fresh):
    report = await hub.conductor.submit_goal(
        "Control hypertension, type 2 diabetes and CKD stage 3 safely", ctx, now=NOW)
    assert report["status"] == "done" and report["template"] == "goal_template.cardiometabolic_ckd"
    subs = {(s["twin"], s["goal_id"]): s for s in report["sub_goals"]}
    assert len(subs) == 5
    trend = subs[("cardiovascular", "cv.hypertensive_trend")]
    assert trend["status"] == "met"
    assert trend["sources"][0]["kb"] == "threshold.hypertension"
    assert trend["sources"][0]["citations"][0] == {
        "source": "who-htn-2021", "section": "3.1 Blood pressure threshold for initiation of "
        "pharmacological treatment", "page": 19}
    assert subs[("renal_urinary", "ren.aki_alert")]["status"] == "not_evaluated"
    assert list(report["orchestrators"]) == ["cardiovascular", "endocrine", "renal_urinary"]


async def test_an_unmatched_goal_runs_nothing(hub, ctx):
    report = await hub.conductor.submit_goal("Improve my mood", ctx)
    assert report["status"] == "unmatched" and report["orchestrators"] == {}


async def test_an_unsafe_plan_is_arbitrated_and_escalated_to_the_clinician(hub, ctx, fresh,
                                                                          runtime):
    report = await hub.conductor.submit_goal(
        "Control hypertension, type 2 diabetes and CKD stage 3 safely", ctx, now=NOW,
        plans=[MSK_EXERCISE, CV_REST])
    assert report["arbitration"]["chosen"] == "cv-monitor"
    assert report["escalations"] == [{
        "to": "clinician", "reason": "arbitration needs a clinician's decision", "risk": 0.1,
        "routed": "apdt"}]


async def test_escalation_is_refused_without_consent(hub, ctx):
    gh = type(ctx)(hdt_id=HDT, actor_role=ctx.actor_role, actor_id="mo-1", purpose="research")
    entry = await hub.conductor.escalate(gh, "risk", 0.4)
    assert entry["routed"] is None and "denied" in entry


async def test_pausing_by_another_agent_is_denied(hub, ctx):
    orchestrator = hub.orchestrator(DTKind.CARDIOVASCULAR)
    with pytest.raises(ActionDenied):
        await hub.conductor.pause(orchestrator, ctx, "x", by="orchestrator-cardiovascular")
    assert not orchestrator.paused


async def test_the_run_route_returns_the_report(app, fresh):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://ahdt") as client:
        headers = {"Authorization": f"Bearer {token(app, Role.MEDICAL_OFFICER)}"}
        body = {"hdt_id": HDT, "twin": "cardiovascular", "now": NOW.isoformat(),
                "probes": ["sign_order_dispense"]}
        resp = await client.post("/v1/agents/run", json=body, headers=headers)
        assert resp.status_code == 200, resp.text
        out = resp.json()
        assert out["kind"] == "orchestrator" and out["summary"]["met"] == 2
        assert out["denials"][0]["action"] == "sign_order_dispense"
        goal = {"hdt_id": HDT, "person_goal": "Control hypertension, type 2 diabetes and CKD "
                "stage 3 safely", "now": NOW.isoformat(), "plans": [MSK_EXERCISE, CV_REST]}
        conducted = (await client.post("/v1/agents/run", json=goal, headers=headers)).json()
        assert conducted["kind"] == "conductor"
        assert conducted["arbitration"]["chosen"] == "cv-monitor"
        both = await client.post("/v1/agents/run", json={**goal, "twin": "cardiovascular"},
                                 headers=headers)
        assert both.status_code == 422
        lab = {"Authorization": f"Bearer {token(app, Role.LAB_SCIENTIST)}"}
        assert (await client.post("/v1/agents/run", json=body, headers=lab)).status_code == 403
