import pytest

from ahdt.agents.guard import ActionDenied
from atra.connectors import DTKind
from atra.contracts import Goal, GoalCheck
from tests.unit.ahdt.agents.conftest import NOW


def goal(**params):
    return Goal(goal_id="g", text="t", owner="twin", priority=3,
                check=GoalCheck(kind="composite", params=params))


def agent_tools(run):
    return {t["tool"] for t in run.report["tool_calls"]}


async def test_the_cardiovascular_orchestrator_meets_its_implemented_checks(hub, ctx, fresh):
    run = await hub.orchestrator(DTKind.CARDIOVASCULAR).run(ctx, now=NOW)
    goals = {g["goal_id"]: g for g in run.report["goals"]}
    assert goals["cv.bp_current"]["status"] == "met"
    assert goals["cv.hypertensive_trend"]["status"] == "met"
    assert goals["cv.hypertensive_trend"]["evidence"]["sources"][0]["kb"] == "goal.cv.forecast_sbp"
    assert goals["cv.detect_arrhythmia"]["status"] == "not_evaluated"
    assert run.report["summary"] == {"met": 2, "unmet": 0, "not_evaluated": 1}
    assert run.result.status == "ok" and run.result.agent == "orchestrator-cardiovascular"
    assert agent_tools(run) == {"ahdt.model.state", "ahdt.data.observations",
                                "ahdt.model.forecast"}
    assert [s["node"] for s in run.report["steps"] if s["node"] in {"sense", "update_state",
                                                                    "plan", "report"}] == [
        "sense", "update_state", "plan", "report"]
    assert all(t.ahdt_layer in (3, 4, 5) for t in run.result.tool_calls)


async def test_stale_observations_leave_the_freshness_goal_unmet(hub, ctx):
    run = await hub.orchestrator(DTKind.CARDIOVASCULAR).run(ctx, now=NOW)
    goals = {g["goal_id"]: g for g in run.report["goals"]}
    assert goals["cv.bp_current"]["status"] == "unmet"
    assert "sbp" in goals["cv.bp_current"]["detail"]
    planned = next(s["planned"] for s in run.report["steps"] if s["node"] == "plan")
    assert planned == ["recommend"]
    assert run.result.proposals == [] and run.result.missing_evidence


async def test_the_endocrine_orchestrator_checks_glucose_freshness(hub, ctx, fresh):
    run = await hub.orchestrator(DTKind.ENDOCRINE).run(ctx, now=NOW)
    goals = {g["goal_id"]: g for g in run.report["goals"]}
    assert goals["endo.state_current"]["status"] == "met"
    assert goals["endo.glycaemic_forecast"]["status"] == "not_evaluated"
    assert "kb holds no value" in goals["endo.glycaemic_forecast"]["detail"]


async def test_a_twin_without_an_implemented_check_reports_not_evaluated(hub, ctx, fresh):
    run = await hub.orchestrator(DTKind.MUSCULOSKELETAL).run(ctx, now=NOW)
    assert {g["status"] for g in run.report["goals"]} == {"not_evaluated"}
    assert run.report["summary"]["met"] == 0


async def test_a_model_output_without_observations_is_not_evaluated(hub, ctx, fresh):
    run = await hub.orchestrator(DTKind.RENAL_URINARY).run(ctx, now=NOW)
    goals = {g["goal_id"]: g for g in run.report["goals"]}
    assert goals["ren.aki_alert"]["status"] == "not_evaluated"
    assert "no recent observations" in goals["ren.aki_alert"]["detail"]
    assert goals["ren.function_current"]["status"] == "unmet"


async def test_a_run_writes_audit_records_for_every_tool_call(hub, ctx, fresh, runtime):
    before = len(runtime.audit)
    run = await hub.orchestrator(DTKind.CARDIOVASCULAR).run(ctx, now=NOW)
    new = list(runtime.audit)[before:]
    assert [r.target for r in new if r.outcome == "ok"].count("show_data:ahdt.model.state") == 1
    assert len(new) >= len(run.result.tool_calls)
    assert all(r.agent and r.hdt_id for r in new)
    assert runtime.audit.verify_chain() == len(runtime.audit)


async def test_a_probe_of_a_never_action_is_denied_and_reported(hub, ctx, fresh, runtime):
    run = await hub.orchestrator(DTKind.CARDIOVASCULAR).run(
        ctx, now=NOW, probes=["sign_order_dispense", "routine_action"])
    assert [d["action"] for d in run.report["denials"]] == ["sign_order_dispense"]
    outcomes = {s["probe"]: s["outcome"] for s in run.report["steps"] if "probe" in s}
    assert outcomes == {"sign_order_dispense": "denied", "routine_action": "allowed"}
    assert any(r.outcome == "denied" and r.target.startswith("sign_order_dispense")
               for r in runtime.audit)


async def test_a_role_without_the_tool_is_denied_inside_the_run(hub, ctx, fresh):
    patient = type(ctx)(hdt_id=ctx.hdt_id, actor_role=type(ctx.actor_role).PATIENT,
                        actor_id="p-1", purpose="care")
    run = await hub.orchestrator(DTKind.CARDIOVASCULAR).run(patient, now=NOW)
    assert run.report["denials"] and run.result.status == "degraded"
    assert {g["status"] for g in run.report["goals"]} <= {"unmet", "not_evaluated"}


async def test_the_recommendation_agent_proposes_only_kb_actions(hub, ctx):
    agent = hub.orchestrator(DTKind.CARDIOVASCULAR).recommendation
    out = await agent.run(goal(), ctx, triggers=["missed_dose"])
    refs = {p.payload["kb_ref"] for p in out.result.proposals}
    assert refs == {"support.adherence/sms_reminder", "support.adherence/reminder_device"}
    assert all(p.status == "proposed" and p.kind == "lifestyle" for p in out.result.proposals)
    assert out.result.proposals[0].payload["sources"][0]["source"] == "who-hiv-2021"


@pytest.mark.parametrize("triggers", [[], ["raised_blood_pressure"]])
async def test_the_recommendation_agent_says_when_the_kb_has_nothing(hub, ctx, triggers):
    agent = hub.orchestrator(DTKind.CARDIOVASCULAR).recommendation
    out = await agent.run(goal(), ctx, triggers=triggers)
    assert out.result.proposals == [] and out.result.missing_evidence


async def test_a_worker_cannot_call_a_tool_outside_its_allow_list(hub, ctx, runtime):
    port = hub.toolbox.port("anomaly-cardiovascular", frozenset({"ahdt.model.state"}), ctx)
    with pytest.raises(ActionDenied):
        await port.call("ahdt.data.genome", genes=["CYP2B6"])
    assert port.denials and list(runtime.audit)[-1].outcome == "denied"


async def test_the_explanation_agent_explains_the_state_of_an_alert(hub, ctx, fresh):
    orchestrator = hub.orchestrator(DTKind.CARDIOVASCULAR)
    state = await orchestrator.monitoring.run(goal(), ctx, fields={}, now=NOW, lookback_s=60)
    out = await orchestrator.explanation.run(goal(), ctx,
                                             output_id=state.data["state"]["output_id"])
    assert out.result.status == "ok" and out.result.explanations and out.data["text"]


async def test_a_paused_orchestrator_does_not_run(hub, ctx):
    orchestrator = hub.orchestrator(DTKind.CARDIOVASCULAR)
    await hub.conductor.pause(orchestrator, ctx, "test")
    run = await orchestrator.run(ctx, now=NOW)
    assert run.result.status == "failed" and run.report["paused"]
    assert run.result.tool_calls == []
    hub.conductor.resume(orchestrator)
