from __future__ import annotations

from typing import Any

from ahdt.agents.toolbox import ToolPort
from ahdt.agents.workers.base import WorkerAgent
from atra import contracts as c
from atra.gateway import CallContext


class ForecastingAgent(WorkerAgent):
    """Forecasts one variable of the twin. `variable` and `horizon_h` come from the goal check
    parameters or from the caller."""

    name = "forecasting"
    tools = frozenset({"ahdt.model.forecast"})

    async def work(self, goal: c.Goal, ctx: CallContext, port: ToolPort,
                   proposals: list[c.Recommendation], explanations: list[str],
                   missing: list[str], **inputs: Any) -> dict[str, Any]:
        params = goal.check.params
        variable = inputs.get("variable", params.get("variable"))
        horizon = inputs.get("horizon_h", params.get("horizon_h"))
        if variable is None or horizon is None:
            missing.append("the goal names no variable or horizon to forecast")
            return {}
        out = await port.call("ahdt.model.forecast", dt=self.twin.value, variable=variable,
                              horizon_h=horizon)
        return {"variable": variable, "horizon_h": horizon, "mean": out["mean"],
                "lower": out["lower"], "upper": out["upper"], "level": out["level"],
                "output_id": out["output_id"]}
