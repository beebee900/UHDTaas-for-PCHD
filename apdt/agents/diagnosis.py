"""The diagnosis orchestrator (design 05, 5.9.2, MSC1):

assemble_evidence -> take_history_if_missing -> rank_differential -> explain -> suggest_tests
-> interrupt accept_diagnosis [medical officer] -> record_working_diagnosis
"""

from __future__ import annotations

import operator
from itertools import pairwise
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from apdt.agents.base import step_of
from apdt.agents.orchestrator import GoalOrchestrator, ask, decision_status
from atra import contracts as c

ALLOWED = ["accept", "edit", "reject", "sign"]
ORDER = ("assemble_evidence", "take_history_if_missing", "rank_differential", "explain",
         "suggest_tests", "accept_diagnosis", "record_working_diagnosis")


class DiagnosisState(TypedDict, total=False):
    run_id: str
    steps: Annotated[list[dict[str, Any]], operator.add]
    recommendation_id: str
    bundle_id: str
    test_recommendation_id: str
    error: str
    decision: dict[str, Any]
    result: dict[str, Any]


class DiagnosisOrchestrator(GoalOrchestrator):
    goal = "diagnosis"

    def build(self) -> StateGraph:
        g = StateGraph(DiagnosisState)
        nodes = {"assemble_evidence": self.assemble_evidence,
                 "take_history_if_missing": self.take_history_if_missing,
                 "rank_differential": self.rank_differential, "explain": self.explain,
                 "suggest_tests": self.suggest_tests, "accept_diagnosis": self.accept_diagnosis,
                 "record_working_diagnosis": self.record_working_diagnosis}
        for name, fn in nodes.items():
            g.add_node(name, self.node(name, fn))
        g.add_edge(START, ORDER[0])
        for a, b in pairwise(ORDER):
            if a != "rank_differential":
                g.add_edge(a, b)
        g.add_conditional_edges("rank_differential",
                                lambda s: END if s.get("error") else "explain", ["explain", END])
        g.add_edge(ORDER[-1], END)
        return g

    async def assemble_evidence(self, state: DiagnosisState, config: Any) -> dict[str, Any]:
        ep, ctx = self.scope(config)
        out = await self.agents.evidence.run(ep, ctx, state["run_id"])
        return {"steps": [step_of("assemble_evidence", out.result, output=out.data)]}

    async def take_history_if_missing(self, state: DiagnosisState, config: Any
                                      ) -> dict[str, Any]:
        ep, ctx = self.scope(config)
        out = await self.agents.history.run(ep, ctx, state["run_id"])
        return {"steps": [step_of("take_history_if_missing", out.result, output=out.data)]}

    async def rank_differential(self, state: DiagnosisState, config: Any) -> dict[str, Any]:
        ep, ctx = self.scope(config)
        out = await self.agents.differential.run(ep, ctx, state["run_id"])
        step = step_of("rank_differential", out.result)
        if out.result.status == "failed":
            return {"error": str(out.data["error"]), "steps": [step]}
        return {"recommendation_id": out.data["recommendation_id"],
                "bundle_id": out.data["bundle_id"] or "", "steps": [step]}

    async def explain(self, state: DiagnosisState, config: Any) -> dict[str, Any]:
        ep, ctx = self.scope(config)
        bundle = self.store.bundles.get(state.get("bundle_id", ""))
        out = await self.agents.evidence.explain(ep, ctx, state["run_id"], bundle)
        return {"steps": [step_of("explain", out.result, output=out.data)]}

    async def suggest_tests(self, state: DiagnosisState, config: Any) -> dict[str, Any]:
        ep, ctx = self.scope(config)
        out = await self.agents.investigation.run(ep, ctx, state["run_id"])
        update: dict[str, Any] = {"steps": [step_of("suggest_tests", out.result)]}
        if out.result.proposals:
            update["test_recommendation_id"] = out.data["recommendation_id"]
        return update

    async def accept_diagnosis(self, state: DiagnosisState, config: Any) -> dict[str, Any]:
        ep, _ = self.scope(config)
        rec = self.store.recommendation(state["recommendation_id"])
        bundle = self.store.bundles.get(rec.bundle_id or "")
        payload = {
            "recommendation_id": rec.recommendation_id, "bundle_id": rec.bundle_id,
            "episode_id": ep.episode_id, "summary": bundle.recommendation.text if bundle else None,
            "blocks_signing": bool(rec.payload.get("blocks_signing", False)),
            "test_recommendation_id": state.get("test_recommendation_id")}
        decision = interrupt(ask("accept_diagnosis", payload, ALLOWED,
                                 c.Role.MEDICAL_OFFICER))
        return {"decision": decision}

    async def record_working_diagnosis(self, state: DiagnosisState, config: Any
                                       ) -> dict[str, Any]:
        ep, _ = self.scope(config)
        decision = c.ClinicalDecision.model_validate(state["decision"])
        rec = await self.record(ep.tenant_id, state["recommendation_id"], decision, True)
        step: dict[str, Any] = {"node": "record_working_diagnosis", "agent": None, "status": "ok",
                "decision": decision.decision, "tool_calls": [], "missing_evidence": []}
        return {"result": decision_status(rec, decision, {}), "steps": [step]}
