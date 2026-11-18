from __future__ import annotations

from typing import Any

from ahdt.agents.toolbox import ToolPort
from ahdt.agents.workers.base import WorkerAgent
from atra import contracts as c
from atra.gateway import CallContext


class ExplanationAgent(WorkerAgent):
    """Requests the explanation of one model output."""

    name = "explanation"
    tools = frozenset({"ahdt.xai.explain"})

    async def work(self, goal: c.Goal, ctx: CallContext, port: ToolPort,
                   proposals: list[c.Recommendation], explanations: list[str],
                   missing: list[str], **inputs: Any) -> dict[str, Any]:
        output_id = inputs.get("output_id")
        if not output_id:
            missing.append("no model output to explain")
            return {}
        out = await port.call("ahdt.xai.explain", output_id=output_id)
        explanations.append(out["explanation_id"])
        return {"explanation_id": out["explanation_id"], "text": out["text"],
                "method_family": out["method_family"], "output_id": output_id}
