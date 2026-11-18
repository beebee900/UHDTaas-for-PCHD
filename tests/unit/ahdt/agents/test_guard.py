import pytest

from ahdt.agents.guard import (
    Approval,
    AutonomyDenied,
    AutonomyPolicy,
    ConsentDenied,
    ProposedAction,
    RoleDenied,
    SourceDenied,
)
from atra.contracts import AutonomyLevel as L
from atra.gateway import Role
from atra.personas import BY_KEY


def action(**kw):
    base = {"agent": "recommendation-cardiovascular", "action_class": "show_data",
            "mode": L.INFORM, "hdt_id": BY_KEY["ao"].hdt_id, "target": "x"}
    return ProposedAction(**{**base, **kw})


def test_autonomy_yaml_holds_the_ahdt_column_of_the_design():
    policy = AutonomyPolicy.load()
    assert {name: rule.level for name, rule in policy.rules.items()} == {
        "show_data": L.INFORM, "clinical_option": L.NEVER, "lifestyle_suggestion": L.RECOMMEND,
        "clinical_record": L.NEVER, "drive_actuator": L.ACT_WITH_APPROVAL,
        "routine_action": L.ACT, "sign_order_dispense": L.NEVER, "pause_orchestrator": L.ACT}


@pytest.mark.parametrize("action_class", ["sign_order_dispense", "clinical_record",
                                          "clinical_option", "unknown_class"])
def test_a_never_action_is_denied_and_audited(hub, ctx, runtime, action_class):
    before = len(runtime.audit)
    with pytest.raises(AutonomyDenied):
        hub.guard.authorise(action(action_class=action_class, mode=L.ACT), ctx)
    record = list(runtime.audit)[-1]
    assert len(runtime.audit) == before + 1
    assert (record.outcome, record.action, record.agent) == (
        "denied", "agent.action", "recommendation-cardiovascular")
    assert record.target.startswith(action_class)
    assert runtime.audit.verify_chain() == len(runtime.audit)


def test_an_action_above_its_level_is_denied_and_one_within_it_runs(hub, ctx, runtime):
    with pytest.raises(AutonomyDenied):
        hub.guard.authorise(action(action_class="lifestyle_suggestion", mode=L.ACT,
                                   kb_ref="support.adherence/cbt"), ctx)
    hub.guard.authorise(action(action_class="lifestyle_suggestion", mode=L.RECOMMEND,
                               kb_ref="support.adherence/cbt"), ctx)
    assert [r.outcome for r in list(runtime.audit)[-2:]] == ["denied", "ok"]


def test_a_clinical_actuator_needs_a_clinician_approval(hub, ctx):
    drive = {"action_class": "drive_actuator", "mode": L.ACT_WITH_APPROVAL}
    with pytest.raises(AutonomyDenied):
        hub.guard.authorise(action(**drive), ctx)
    with pytest.raises(AutonomyDenied):
        hub.guard.authorise(action(**drive, approval=Approval("c-1", Role.CARER)), ctx)
    hub.guard.authorise(action(**drive, approval=Approval("mo-1", Role.MEDICAL_OFFICER)), ctx)
    with pytest.raises(AutonomyDenied):
        hub.guard.authorise(action(action_class="drive_actuator", mode=L.ACT), ctx)


def test_a_suggestion_must_cite_the_kb(hub, ctx):
    with pytest.raises(SourceDenied):
        hub.guard.authorise(action(action_class="lifestyle_suggestion", mode=L.RECOMMEND), ctx)


def test_only_the_conductor_pauses_an_orchestrator(hub, ctx):
    pause = {"action_class": "pause_orchestrator", "mode": L.ACT}
    with pytest.raises(RoleDenied):
        hub.guard.authorise(action(agent="orchestrator-cardiovascular", **pause), ctx)
    hub.guard.authorise(action(agent="ahdt-conductor", **pause), ctx)


def test_the_guard_checks_role_tool_allow_list_and_consent(hub, ctx, runtime):
    read = {"tool": "ahdt.model.state"}
    with pytest.raises(RoleDenied):
        hub.guard.authorise(action(tool="ahdt.data.imaging", allow=frozenset({"x"})), ctx)
    other = type(ctx)(hdt_id=ctx.hdt_id, actor_role=Role.LAB_SCIENTIST, actor_id="l-1")
    with pytest.raises(RoleDenied):
        hub.guard.authorise(action(**read), other)
    gh = BY_KEY["gh"].hdt_id
    with pytest.raises(ConsentDenied):
        hub.guard.authorise(action(tool="ahdt.data.genome", hdt_id=gh), ctx)
    research = type(ctx)(hdt_id=ctx.hdt_id, actor_role=ctx.actor_role, actor_id="mo-1",
                         purpose="research")
    with pytest.raises(ConsentDenied):
        hub.guard.authorise(action(**read), research)
    hub.guard.authorise(action(**read), ctx)
