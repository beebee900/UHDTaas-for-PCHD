from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from ahdt.agents.toolbox import ToolPort
from ahdt.agents.workers.base import WorkerAgent
from atra import contracts as c
from atra.gateway import CallContext


class MonitoringAgent(WorkerAgent):
    """Keeps the twin's state current and reports when each of its fields was last observed.

    Asking for the state runs the estimator step. `fields` maps a field name to its LOINC
    code; the agent looks back `lookback_s` seconds from `now`."""

    name = "monitoring"
    tools = frozenset({"ahdt.model.state", "ahdt.data.observations"})

    async def work(self, goal: c.Goal, ctx: CallContext, port: ToolPort,
                   proposals: list[c.Recommendation], explanations: list[str],
                   missing: list[str], **inputs: Any) -> dict[str, Any]:
        state = await port.call("ahdt.model.state", dt=self.twin.value)
        fields: dict[str, str] = inputs.get("fields", {})
        now: datetime = inputs["now"]
        last_seen: dict[str, datetime | None] = {name: None for name in fields}
        if fields:
            start = now - timedelta(seconds=inputs["lookback_s"])
            series = (await port.call(
                "ahdt.data.observations", codes=sorted(set(fields.values())),
                period={"start": start, "end": now}))["series"]
            for name, code in fields.items():
                times = [p["t"] for p in series.get(code, ())]
                last_seen[name] = max(times) if times else None
        return {"state": state, "last_seen": last_seen}
