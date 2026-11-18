from __future__ import annotations

from typing import Any

from ahdt.agents.toolbox import ToolPort
from ahdt.agents.workers.base import WorkerAgent
from atra import contracts as c
from atra.gateway import CallContext

SEVERITIES = ("normal", "watch", "alert")


class AnomalyAgent(WorkerAgent):
    """Grades the twin's state as normal, watch or alert. The grade comes from the model
    service. The agent reads the state itself when the caller passes none."""

    name = "anomaly"
    tools = frozenset({"ahdt.model.state"})

    async def work(self, goal: c.Goal, ctx: CallContext, port: ToolPort,
                   proposals: list[c.Recommendation], explanations: list[str],
                   missing: list[str], **inputs: Any) -> dict[str, Any]:
        state = inputs.get("state") or await port.call("ahdt.model.state", dt=self.twin.value)
        severity = state.get("status")
        if severity not in SEVERITIES:
            missing.append("the model service returned no severity")
            return {"severity": None, "anomaly": False}
        return {"severity": severity, "anomaly": severity != "normal",
                "output_id": state.get("output_id")}
