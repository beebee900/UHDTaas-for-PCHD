"""Common shape of the worker agents."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal

from ahdt.agents.guard import ActionDenied
from ahdt.agents.toolbox import ToolBox, ToolPort
from atra import contracts as c
from atra.connectors import DTKind
from atra.gateway import CallContext


@dataclass
class WorkerOutput:
    """The contract result of one run, plus the findings the orchestrator reads."""

    result: c.AgentResult
    data: dict[str, Any] = field(default_factory=dict)
    denials: list[dict[str, str]] = field(default_factory=list)


class WorkerAgent:
    """Implements the `Agent` protocol (design 03, 3.10). Subclasses set `name` and `tools`
    and write `work`; a worker calls only the tools in its allow-list."""

    name: ClassVar[str]
    tier: ClassVar[Literal["7.1"]] = "7.1"
    tools: ClassVar[frozenset[str]] = frozenset()
    level: ClassVar[c.AutonomyLevel] = c.AutonomyLevel.INFORM

    def __init__(self, twin: DTKind, toolbox: ToolBox) -> None:
        self.twin = twin
        self.toolbox = toolbox

    async def act(self, goal: c.Goal, ctx: CallContext) -> c.AgentResult:
        return (await self.run(goal, ctx)).result

    async def run(self, goal: c.Goal, ctx: CallContext, **inputs: Any) -> WorkerOutput:
        port = self.toolbox.port(self.name, self.tools, ctx)
        proposals: list[c.Recommendation] = []
        explanations: list[str] = []
        missing: list[str] = []
        data: dict[str, Any] = {}
        status: Literal["ok", "degraded", "failed"] = "ok"
        try:
            data = await self.work(goal, ctx, port, proposals, explanations, missing, **inputs)
        except ActionDenied as denied:
            status, missing = "failed", [denied.reason]
        except Exception as exc:  # a tool failure degrades this run only
            status, missing = "failed", [f"{type(exc).__name__}: {exc}"]
        result = c.AgentResult(agent=f"{self.name}-{self.twin.value}", goal_id=goal.goal_id,
                               proposals=proposals, tool_calls=port.calls,
                               explanations=explanations, autonomy_level=self.level,
                               status=status, missing_evidence=missing)
        return WorkerOutput(result, data, port.denials)

    async def work(self, goal: c.Goal, ctx: CallContext, port: ToolPort,
                   proposals: list[c.Recommendation], explanations: list[str],
                   missing: list[str], **inputs: Any) -> dict[str, Any]:
        raise NotImplementedError
