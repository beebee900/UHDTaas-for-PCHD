from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from ahdt.agents.guard import ActionDenied, ProposedAction
from ahdt.agents.toolbox import ToolBox, ToolPort
from ahdt.agents.workers.base import WorkerAgent
from atra import contracts as c
from atra.connectors import DTKind
from atra.gateway import CallContext
from atra.ids import new_record_id
from atra.kb import KnowledgeBase

SUPPORT_PREFIX = "support."


class RecommendationAgent(WorkerAgent):
    """Proposes behaviour-change and support actions that the kb lists for the given triggers.
    Nothing outside `kb/support_actions.yaml` is proposed. When the kb has no action for the
    triggers, the run proposes nothing and names the gap in `missing_evidence`."""

    name = "recommendation"
    level = c.AutonomyLevel.RECOMMEND

    def __init__(self, twin: DTKind, toolbox: ToolBox, kb: KnowledgeBase) -> None:
        super().__init__(twin, toolbox)
        self.kb = kb

    def candidates(self, triggers: Sequence[str]) -> list[dict[str, Any]]:
        found = []
        for entry_id in self.kb.ids():
            if not entry_id.startswith(SUPPORT_PREFIX):
                continue
            entry = self.kb.entry(entry_id)
            for action in entry.content().get("actions", ()):
                hit = sorted(set(action.get("triggers", ())) & set(triggers))
                if hit:
                    found.append({"entry": entry_id, "action": action, "triggers": hit,
                                  "source": entry.provenance.citations()})
        return found

    async def work(self, goal: c.Goal, ctx: CallContext, port: ToolPort,
                   proposals: list[c.Recommendation], explanations: list[str],
                   missing: list[str], **inputs: Any) -> dict[str, Any]:
        triggers = list(inputs.get("triggers", ()))
        if not triggers:
            missing.append("no trigger names a support action to look up")
            return {"considered": 0}
        found = self.candidates(triggers)
        if not found:
            missing.append(f"kb/support_actions.yaml has no action for: {', '.join(triggers)}")
            return {"considered": 0}
        for item in found:
            action = item["action"]
            ref = f"{item['entry']}/{action['id']}"
            try:
                self.toolbox.guard.authorise(ProposedAction(
                    agent=f"{self.name}-{self.twin.value}", hdt_id=ctx.hdt_id, target=ref,
                    action_class="lifestyle_suggestion", mode=c.AutonomyLevel.RECOMMEND,
                    kb_ref=ref), ctx)
            except ActionDenied as denied:
                port.denials.append({"agent": f"{self.name}-{self.twin.value}", "action": ref,
                                     "reason": denied.reason})
                continue
            proposals.append(c.Recommendation(
                recommendation_id=new_record_id(), episode_id=ctx.episode_id, hdt_id=ctx.hdt_id,
                kind="lifestyle",
                payload={"kb_ref": ref, "label": action["label"], "channel": action["channel"],
                         "certainty": action.get("certainty"), "triggers": item["triggers"],
                         "sources": [s.model_dump(exclude_none=True) for s in item["source"]]},
                status="proposed", autonomy_level=self.level,
                created_by_agent=f"{self.name}-{self.twin.value}"))
        return {"considered": len(found)}
