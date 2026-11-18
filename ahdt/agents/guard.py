"""Safety and consent guard (design 04, 4.9.1) over the autonomy levels of design 03, 3.14.

Every action an agent proposes passes `SafetyGuard.authorise` before it runs. The guard
checks the action class against the level in `autonomy.yaml`, then the agent, the caller's
role, the person's consent and, for classes that need one, the kb source. Each decision is
written to the audit log; a refusal raises a subclass of `ActionDenied`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from atra.consent import ConsentRegistry
from atra.contracts import AutonomyLevel
from atra.gateway import DEFAULT_ROLE_TOOLS, CallContext, Role
from atra.provenance import AuditLog

AUTONOMY_FILE = Path(__file__).resolve().parent.parent / "autonomy.yaml"

# Autonomy grows with the rank. `never` has no rank: it permits nothing.
RANK: Mapping[AutonomyLevel, int] = {
    AutonomyLevel.INFORM: 0, AutonomyLevel.RECOMMEND: 1,
    AutonomyLevel.PREPARE_FOR_SIGNATURE: 2, AutonomyLevel.ACT_WITH_APPROVAL: 3,
    AutonomyLevel.ACT: 4,
}


class ActionDenied(PermissionError):
    """The guard refused an action."""

    def __init__(self, reason: str, action: ProposedAction) -> None:
        super().__init__(reason)
        self.reason = reason
        self.action = action


class AutonomyDenied(ActionDenied):
    """The action is above the autonomy level of its class."""


class ConsentDenied(ActionDenied):
    """The person's consent does not cover the action."""


class RoleDenied(ActionDenied):
    """The agent or the acting role may not take the action."""


class SourceDenied(ActionDenied):
    """The action cites no kb source."""


@dataclass(frozen=True)
class Approval:
    approver_id: str
    approver_role: Role


@dataclass(frozen=True)
class ProposedAction:
    """What an agent wants to do, and the autonomy it wants to do it with."""

    agent: str
    action_class: str
    mode: AutonomyLevel
    hdt_id: str
    target: str
    tool: str | None = None
    kb_ref: str | None = None
    approval: Approval | None = None
    allow: frozenset[str] | None = None


@dataclass(frozen=True)
class ActionRule:
    level: AutonomyLevel
    agents: frozenset[str] | None = None
    kb_source_required: bool = False


@dataclass
class AutonomyPolicy:
    rules: Mapping[str, ActionRule]
    approver_roles: frozenset[Role] = field(default_factory=frozenset)

    @classmethod
    def load(cls, path: Path = AUTONOMY_FILE) -> AutonomyPolicy:
        raw: Mapping[str, Any] = yaml.safe_load(path.read_text(encoding="utf-8"))
        rules = {
            name: ActionRule(AutonomyLevel(body["level"]),
                             frozenset(body["agents"]) if "agents" in body else None,
                             bool(body.get("kb_source_required", False)))
            for name, body in raw["actions"].items()}
        return cls(rules, frozenset(Role(r) for r in raw.get("approver_roles", ())))

    def level(self, action_class: str) -> AutonomyLevel:
        rule = self.rules.get(action_class)
        return rule.level if rule else AutonomyLevel.NEVER


class SafetyGuard:
    def __init__(self, audit: AuditLog, consents: ConsentRegistry,
                 policy: AutonomyPolicy | None = None) -> None:
        self.audit = audit
        self.consents = consents
        self.policy = policy or AutonomyPolicy.load()

    def authorise(self, action: ProposedAction, ctx: CallContext) -> None:
        """Raise `ActionDenied` when the action may not run; audit the decision either way."""
        try:
            self._check(action, ctx)
        except ActionDenied as denied:
            self._audit(action, ctx, "denied", denied.reason)
            raise
        self._audit(action, ctx, "ok", None)

    def _check(self, action: ProposedAction, ctx: CallContext) -> None:
        rule = self.policy.rules.get(action.action_class)
        level = rule.level if rule else AutonomyLevel.NEVER
        if rule is None or level is AutonomyLevel.NEVER or RANK[action.mode] > RANK[level]:
            raise AutonomyDenied(
                f"{action.action_class} is limited to '{level.value}' and was attempted as "
                f"'{action.mode.value}'", action)
        if rule.agents is not None and action.agent not in rule.agents:
            raise RoleDenied(f"{action.agent} may not take {action.action_class} actions",
                             action)
        if action.mode is AutonomyLevel.ACT_WITH_APPROVAL and (
                action.approval is None
                or action.approval.approver_role not in self.policy.approver_roles):
            raise AutonomyDenied(f"{action.action_class} needs a clinician's approval", action)
        if action.tool is not None and action.allow is not None and (
                action.tool not in action.allow):
            raise RoleDenied(f"{action.agent} may not call {action.tool}", action)
        if action.tool is not None and action.tool not in DEFAULT_ROLE_TOOLS.get(
                ctx.actor_role, frozenset()):
            raise RoleDenied(f"role {ctx.actor_role.value} may not use {action.tool}", action)
        consent = self.consents.get(action.hdt_id)
        if consent is None or ctx.purpose not in consent.purposes:
            raise ConsentDenied(f"no consent for purpose '{ctx.purpose}'", action)
        if action.tool is not None and action.tool in consent.refused_tools:
            raise ConsentDenied(f"the person withheld {action.tool}", action)
        if rule.kb_source_required and not action.kb_ref:
            raise SourceDenied(f"{action.action_class} must cite a kb entry", action)

    def _audit(self, action: ProposedAction, ctx: CallContext, outcome: Any,
               reason: str | None) -> None:
        self.audit.append(
            actor={"id": ctx.actor_id, "role": ctx.actor_role.value}, agent=action.agent,
            hdt_id=action.hdt_id or None, episode_id=ctx.episode_id, action="agent.action",
            target=f"{action.action_class}:{action.tool or action.target}", purpose=ctx.purpose,
            outcome=outcome, reason=reason)
