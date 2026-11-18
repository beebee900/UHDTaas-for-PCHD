"""The Safety and consent guard (design 05, 5.9.1; autonomy levels in 03, 3.14).

Every agent action passes `authorise` before it runs. An action outside the agent's tool
allow-list or action classes, or in a class whose APDT level is `never` (sign, order,
dispense, change treatment, drive an actuator), raises `AutonomyDenied` and is audited with
outcome `denied`.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal

from atra import contracts as c
from atra.gateway import CallContext
from atra.provenance import AuditLog

# Action class -> APDT autonomy level (03, 3.14).
ACTION_LEVELS: Mapping[str, c.AutonomyLevel] = {
    "show_data": c.AutonomyLevel.INFORM,
    "recommend": c.AutonomyLevel.RECOMMEND,
    "lifestyle_suggestion": c.AutonomyLevel.RECOMMEND,
    "prepare_record": c.AutonomyLevel.PREPARE_FOR_SIGNATURE,
    "notify": c.AutonomyLevel.ACT,
    "pause_orchestrator": c.AutonomyLevel.ACT,
    "drive_actuator": c.AutonomyLevel.NEVER,
    "sign": c.AutonomyLevel.NEVER,
    "order": c.AutonomyLevel.NEVER,
    "dispense": c.AutonomyLevel.NEVER,
    "change_treatment": c.AutonomyLevel.NEVER}


class AutonomyDenied(PermissionError):
    def __init__(self, agent: str, action: str, reason: str) -> None:
        super().__init__(f"{agent} may not {action}: {reason}")
        self.agent = agent
        self.action = action
        self.reason = reason


class SafetyConsentGuard:
    name = "safety-consent-guard"
    tier: Literal["7.1", "7.2", "7.3"] = "7.1"
    twin: Literal["apdt"] = "apdt"
    tools = frozenset({"apdt.policy.check"})
    actions = frozenset({"show_data"})

    def __init__(self, audit: AuditLog) -> None:
        self.audit = audit

    def authorise(self, agent: Any, action: str, *, tenant_id: str, ctx: CallContext,
                  tool: str | None = None, target: str = "") -> c.AutonomyLevel:
        reason = self._violation(agent, action, tool)
        if reason is not None:
            self.audit.append(
                actor={"id": agent.name, "role": ctx.actor_role.value}, tenant_id=tenant_id,
                hdt_id=ctx.hdt_id, episode_id=ctx.episode_id, action=f"agent.{action}",
                target=target or tool or action, purpose=ctx.purpose, outcome="denied",
                reason=reason)
            raise AutonomyDenied(agent.name, action, reason)
        return ACTION_LEVELS[action]

    @staticmethod
    def _violation(agent: Any, action: str, tool: str | None) -> str | None:
        level = ACTION_LEVELS.get(action)
        if level is None:
            return f"unknown action class {action}"
        if level == c.AutonomyLevel.NEVER:
            return "the autonomy level for this action class is never"
        if action not in agent.actions:
            return f"{action} is not an action class of {agent.name}"
        if tool is not None and tool not in agent.tools:
            return f"{tool} is not on the tool allow-list"
        return None

    async def act(self, goal: c.Goal, ctx: CallContext) -> c.AgentResult:
        """Checks the action class named in `goal.check.params["action"]` for an agent."""
        action = str(goal.check.params.get("action", "show_data"))
        level = ACTION_LEVELS.get(action)
        ok = level is not None and level != c.AutonomyLevel.NEVER
        return c.AgentResult(
            agent=self.name, goal_id=goal.goal_id,
            autonomy_level=level or c.AutonomyLevel.NEVER, status="ok" if ok else "failed",
            missing_evidence=[] if ok else [f"{action} is not permitted for agents"])
