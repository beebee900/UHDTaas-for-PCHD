"""Shared machinery of the APDT agents: guarded tool calls with a trace span and a record."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from apdt.agents.guard import SafetyConsentGuard
from apdt.services.ahdt_access import Missing
from apdt.services.memory_store import InMemoryEpisodeStore
from atra import contracts as c
from atra.gateway import CallContext
from atra.telemetry import tracer

AHDT_LAYER: Mapping[str, int] = {"ahdt.data": 3, "ahdt.model": 4, "ahdt.xai": 5}
spans = tracer("apdt")


@dataclass
class Outcome:
    """What one agent run returns: the contract result and the data the graph carries on."""
    result: c.AgentResult
    data: dict[str, Any] = field(default_factory=dict)


class ToolKit:
    """The tool calls of one agent run. Every call passes the guard first."""

    def __init__(self, agent: BaseAgent, guard: SafetyConsentGuard, tenant_id: str,
                 ctx: CallContext) -> None:
        self.agent = agent
        self.guard = guard
        self.tenant_id = tenant_id
        self.ctx = ctx
        self.calls: list[c.ToolCallRecord] = []
        self.missing: list[str] = []

    async def use[T](self, tool: str, action: str, args: Mapping[str, Any],
                     fn: Callable[[], Awaitable[T]]) -> T:
        self.guard.authorise(self.agent, action, tenant_id=self.tenant_id, ctx=self.ctx,
                             tool=tool)
        digest = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()
                                ).hexdigest()[:16]
        layer = next((v for k, v in AHDT_LAYER.items() if tool.startswith(k)), None)
        self.calls.append(c.ToolCallRecord(tool=tool, args_hash=digest,
                                           result_ref=f"{tool}:{digest}", ahdt_layer=layer))
        with spans.start_as_current_span(f"apdt.tool.{tool}",
                                         attributes={"apdt.agent": self.agent.name}):
            return await fn()

    async def optional[T](self, tool: str, action: str, args: Mapping[str, Any],
                          fn: Callable[[], Awaitable[T]]) -> T | None:
        """Like `use`, but an AHDT call that gives no data is listed as missing evidence."""
        try:
            return await self.use(tool, action, args, fn)
        except Missing as exc:
            self.missing.append(str(exc))
            return None

    def attempt(self, action: str, target: str) -> None:
        """An action that the guard decides on; used for sign, order, dispense and the like."""
        self.guard.authorise(self.agent, action, tenant_id=self.tenant_id, ctx=self.ctx,
                             target=target)


class BaseAgent:
    name: ClassVar[str]
    tier: ClassVar[Literal["7.1", "7.2", "7.3"]] = "7.1"
    twin: ClassVar[Literal["apdt"]] = "apdt"
    tools: ClassVar[frozenset[str]]
    actions: ClassVar[frozenset[str]]
    autonomy: ClassVar[c.AutonomyLevel] = c.AutonomyLevel.RECOMMEND

    def __init__(self, guard: SafetyConsentGuard, store: InMemoryEpisodeStore) -> None:
        self.guard = guard
        self.store = store

    def kit(self, ep: c.Episode, ctx: CallContext) -> ToolKit:
        return ToolKit(self, self.guard, ep.tenant_id, ctx)

    def outcome(self, goal_id: str, kit: ToolKit, data: dict[str, Any], *,
                proposals: list[c.Recommendation] | None = None,
                explanations: list[str] | None = None, failed: bool = False) -> Outcome:
        status: Literal["ok", "degraded", "failed"] = (
            "failed" if failed else "degraded" if kit.missing else "ok")
        return Outcome(c.AgentResult(
            agent=self.name, goal_id=goal_id, proposals=proposals or [],
            tool_calls=kit.calls, explanations=explanations or [], autonomy_level=self.autonomy,
            status=status, missing_evidence=kit.missing), data)

    async def run(self, ep: c.Episode, ctx: CallContext, goal_id: str) -> Outcome:
        raise NotImplementedError

    async def act(self, goal: c.Goal, ctx: CallContext) -> c.AgentResult:
        """Runs the agent on the episode named by `goal.owner` (tenant in `check.params`)."""
        ep = self.store.get(str(goal.check.params["tenant_id"]), goal.owner)
        return (await self.run(ep, ctx, goal.goal_id)).result


def step_of(node: str, result: c.AgentResult, **extra: Any) -> dict[str, Any]:
    """The run-result entry for one graph node: which agent acted and with which tools."""
    return {"node": node, "agent": result.agent, "status": result.status,
            "autonomy_level": result.autonomy_level.value,
            "tool_calls": [t.model_dump(mode="json") for t in result.tool_calls],
            "missing_evidence": list(result.missing_evidence), **extra}
