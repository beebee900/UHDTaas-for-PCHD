import pytest

from apdt.agents import AutonomyDenied, SafetyConsentGuard
from apdt.agents.clinical import DifferentialDiagnosisAgent
from atra.contracts import Role
from atra.gateway import CallContext
from atra.provenance import AuditLog

CTX = CallContext("hdt-1", Role.MEDICAL_OFFICER, "medical_officer.fac-a", "care", "ep-1")


def make() -> tuple[AuditLog, SafetyConsentGuard, DifferentialDiagnosisAgent]:
    audit = AuditLog("apdt")
    guard = SafetyConsentGuard(audit)
    return audit, guard, DifferentialDiagnosisAgent(guard, None, None)  # type: ignore[arg-type]


@pytest.mark.parametrize("action", ["sign", "order", "dispense", "change_treatment",
                                    "drive_actuator"])
def test_actions_at_level_never_are_denied_and_audited(action: str) -> None:
    audit, guard, agent = make()
    with pytest.raises(AutonomyDenied):
        guard.authorise(agent, action, tenant_id="fac-a", ctx=CTX, target="rec-1")
    [rec] = audit.query(outcome="denied")
    assert rec.action == f"agent.{action}" and rec.target == "rec-1"
    assert rec.actor.id == agent.name and rec.tenant_id == "fac-a"


def test_a_tool_off_the_allow_list_is_denied() -> None:
    audit, guard, agent = make()
    with pytest.raises(AutonomyDenied, match="allow-list"):
        guard.authorise(agent, "recommend", tenant_id="fac-a", ctx=CTX, tool="ahdt.data.genome")
    assert len(audit.query(outcome="denied")) == 1


def test_an_allowed_action_passes_without_an_audit_record() -> None:
    audit, guard, agent = make()
    guard.authorise(agent, "recommend", tenant_id="fac-a", ctx=CTX,
                    tool="apdt.models.differential")
    assert len(audit) == 0
