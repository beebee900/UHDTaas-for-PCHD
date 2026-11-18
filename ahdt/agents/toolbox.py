"""The only way an agent reaches the Layer 6 tools: allow-list, guard, handler, record."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from ahdt.agents.guard import ActionDenied, ProposedAction, SafetyGuard
from atra import contracts as c
from atra.gateway import AHDT_TOOLS, CallContext
from atra.security import Claims
from atra.service import Identity, ToolHandler

LAYER_OF = {t.name: t.reaches_layer for t in AHDT_TOOLS}
ROUTINE_TOOLS = frozenset({"ahdt.cognitive.request_data"})


class ToolPort:
    """Tool calls of one agent for one request. Collects the call records and the denials."""

    def __init__(self, handlers: Mapping[str, ToolHandler], guard: SafetyGuard, agent: str,
                 allow: frozenset[str], ctx: CallContext, tenant_id: str | None) -> None:
        self._handlers = handlers
        self._guard = guard
        self.agent = agent
        self.allow = allow
        self.ctx = ctx
        self.calls: list[c.ToolCallRecord] = []
        self.denials: list[dict[str, str]] = []
        claims = Claims(sub=ctx.actor_id, role=ctx.actor_role, iss="ahdt.agents", aud="ahdt",
                        exp=0, iat=0, hdt_id=ctx.hdt_id, tenant_id=tenant_id)
        self._identity = Identity(claims, ctx, False, tenant_id)

    async def call(self, tool: str, **args: Any) -> dict[str, Any]:
        """Run `tool` for the context's person. Raises `ActionDenied` when refused."""
        routine = tool in ROUTINE_TOOLS
        action = ProposedAction(
            agent=self.agent, hdt_id=self.ctx.hdt_id, tool=tool, target=tool, allow=self.allow,
            action_class="routine_action" if routine else "show_data",
            mode=c.AutonomyLevel.ACT if routine else c.AutonomyLevel.INFORM)
        try:
            self._guard.authorise(action, self.ctx)
        except ActionDenied as denied:
            self.denials.append({"agent": self.agent, "action": tool, "reason": denied.reason})
            raise
        payload = {"hdt_id": self.ctx.hdt_id, **args}
        parsed = c.TOOL_ARGS[tool].model_validate(payload)
        result = dict(await self._handlers[tool](parsed, self._identity))
        result.pop("_meta", None)
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode())
        ref = str(result.get("output_id") or hashlib.sha256(
            json.dumps(result, sort_keys=True, default=str).encode()).hexdigest()[:16])
        self.calls.append(c.ToolCallRecord(tool=tool, args_hash=digest.hexdigest()[:16],
                                           result_ref=ref, ahdt_layer=LAYER_OF.get(tool)))
        return result


class ToolBox:
    """The service handlers, the guard and the tenant that the ports of one app share."""

    def __init__(self, handlers: Mapping[str, ToolHandler], guard: SafetyGuard,
                 tenant_id: str | None = None) -> None:
        self.handlers = handlers
        self.guard = guard
        self.tenant_id = tenant_id

    def port(self, agent: str, allow: frozenset[str], ctx: CallContext) -> ToolPort:
        return ToolPort(self.handlers, self.guard, agent, allow, ctx, self.tenant_id)
