"""The treatment orchestrator (design 05, 5.9.2, MSC2):

enumerate_options -> check_options -> simulate_each -> explain
-> interrupt select_and_sign [medical officer] -> interrupt verify_prescription [pharmacist]

A reject at the first interrupt ends the run. The patient's consent interrupt is not part of
this graph.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from apdt.agents import AgentSet
from apdt.agents.base import step_of
from apdt.agents.orchestrator import GoalOrchestrator, Record, ask, decision_status
from apdt.models.treatment.options import Option
from apdt.services.memory_store import InMemoryEpisodeStore
from atra import contracts as c

SIGN_ALLOWED = ["sign", "edit", "reject"]
VERIFY_ALLOWED = ["verify", "query", "reject"]
MAX_SIMULATED = 3


class TreatmentState(TypedDict, total=False):
    run_id: str
    steps: Annotated[list[dict[str, Any]], operator.add]
    recommendation_id: str
    bundle_id: str
    options: list[dict[str, Any]]
    checks: list[dict[str, Any]]
    simulations: list[dict[str, Any]]
    error: str
    sign_decision: dict[str, Any]
    verify_decision: dict[str, Any]
    result: dict[str, Any]


class TreatmentOrchestrator(GoalOrchestrator):
    goal = "treatment"

    def __init__(self, agents: AgentSet, store: InMemoryEpisodeStore, record: Record) -> None:
        self._options: dict[str, list[Option]] = {}
        super().__init__(agents, store, record)

    def settle(self, run_id: str) -> None:
        self._options.pop(run_id, None)

    def build(self) -> StateGraph:
        g = StateGraph(TreatmentState)
        for name, fn in {
                "enumerate_options": self.enumerate_options, "check_options": self.check_options,
                "simulate_each": self.simulate_each, "explain": self.explain,
                "select_and_sign": self.select_and_sign, "record_signature": self.record_signature,
                "verify_prescription": self.verify_prescription,
                "record_verification": self.record_verification}.items():
            g.add_node(name, self.node(name, fn))
        g.add_edge(START, "enumerate_options")
        g.add_conditional_edges("enumerate_options",
                                lambda s: END if s.get("error") else "check_options",
                                ["check_options", END])
        g.add_edge("check_options", "simulate_each")
        g.add_edge("simulate_each", "explain")
        g.add_edge("explain", "select_and_sign")
        g.add_edge("select_and_sign", "record_signature")
        g.add_conditional_edges(
            "record_signature",
            lambda s: END if s["sign_decision"]["decision"] == "reject" else "verify_prescription",
            ["verify_prescription", END])
        g.add_edge("verify_prescription", "record_verification")
        g.add_edge("record_verification", END)
        return g

    async def enumerate_options(self, state: TreatmentState, config: Any) -> dict[str, Any]:
        ep, ctx = self.scope(config)
        out, options = await self.agents.treatment.enumerate(ep, ctx, state["run_id"])
        step = step_of("enumerate_options", out.result)
        if out.result.status == "failed":
            return {"error": str(out.data["error"]), "steps": [step]}
        self._options[state["run_id"]] = options
        return {"recommendation_id": out.data["recommendation_id"],
                "bundle_id": out.data["bundle_id"] or "", "options": out.data["options"],
                "steps": [step]}

    async def check_options(self, state: TreatmentState, config: Any) -> dict[str, Any]:
        ep, ctx = self.scope(config)
        out = await self.agents.pharmacotherapy.check(
            ep, ctx, state["run_id"], self._options[state["run_id"]])
        return {"checks": out.data["checks"],
                "steps": [step_of("check_options", out.result, output=out.data)]}

    async def simulate_each(self, state: TreatmentState, config: Any) -> dict[str, Any]:
        ep, ctx = self.scope(config)
        options = self._options[state["run_id"]][:MAX_SIMULATED]
        out = await self.agents.treatment.simulate_each(ep, ctx, state["run_id"], options)
        return {"simulations": out.data["simulations"],
                "steps": [step_of("simulate_each", out.result, output=out.data)]}

    async def explain(self, state: TreatmentState, config: Any) -> dict[str, Any]:
        ep, ctx = self.scope(config)
        bundle = self.store.bundles.get(state.get("bundle_id", ""))
        out = await self.agents.evidence.explain(ep, ctx, state["run_id"], bundle)
        return {"steps": [step_of("explain", out.result, output=out.data)]}

    def payload(self, state: TreatmentState, ep: c.Episode) -> dict[str, Any]:
        rec = self.store.recommendation(state["recommendation_id"])
        bundle = self.store.bundles.get(rec.bundle_id or "")
        sims = {s["option_id"]: s for s in state.get("simulations", [])}
        checks = {k["option_id"]: k for k in state.get("checks", [])}
        options = []
        for o in state.get("options", []):
            sim = sims.get(o["option_id"])
            check = checks.get(o["option_id"], {})
            options.append({
                **o, "issues": check.get("issues", []),
                "simulation": (sim["simulation"] or {}).get("summary") if sim else None,
                "simulation_error": sim["error"] if sim else None})
        return {"recommendation_id": rec.recommendation_id, "bundle_id": rec.bundle_id,
                "episode_id": ep.episode_id,
                "summary": bundle.recommendation.text if bundle else None,
                "blocks_signing": bool(rec.payload.get("blocks_signing", False)),
                "options": options}

    async def select_and_sign(self, state: TreatmentState, config: Any) -> dict[str, Any]:
        ep, _ = self.scope(config)
        decision = interrupt(ask("sign_prescription", self.payload(state, ep), SIGN_ALLOWED,
                                 c.Role.MEDICAL_OFFICER))
        return {"sign_decision": decision}

    async def record_signature(self, state: TreatmentState, config: Any) -> dict[str, Any]:
        ep, _ = self.scope(config)
        decision = c.ClinicalDecision.model_validate(state["sign_decision"])
        rec = await self.record(ep.tenant_id, state["recommendation_id"], decision, True)
        step = _record_step("record_signature", decision)
        if decision.decision == "reject":
            return {"result": decision_status(rec, decision, {}), "steps": [step]}
        return {"steps": [step]}

    async def verify_prescription(self, state: TreatmentState, config: Any) -> dict[str, Any]:
        ep, _ = self.scope(config)
        decision = interrupt(ask("verify_prescription", self.payload(state, ep), VERIFY_ALLOWED,
                                 c.Role.PHARMACIST))
        return {"verify_decision": decision}

    async def record_verification(self, state: TreatmentState, config: Any) -> dict[str, Any]:
        ep, _ = self.scope(config)
        decision = c.ClinicalDecision.model_validate(state["verify_decision"])
        rec = await self.record(ep.tenant_id, state["recommendation_id"], decision,
                                decision.decision == "reject")
        signed = c.ClinicalDecision.model_validate(state["sign_decision"])
        return {"result": decision_status(rec, decision, {"signed_by": signed.decided_by.id}),
                "steps": [_record_step("record_verification", decision)]}


def _record_step(node: str, decision: c.ClinicalDecision) -> dict[str, Any]:
    return {"node": node, "agent": None, "status": "ok", "decision": decision.decision,
            "tool_calls": [], "missing_evidence": []}
