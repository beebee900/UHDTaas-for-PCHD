"""Base of the 7.2 goal orchestrators: a LangGraph `StateGraph` with one checkpointer thread
per run (design 05, 5.9.2). Interrupt nodes call `interrupt()` and the run resumes with
`Command(resume=<ClinicalDecision>)`."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, ClassVar

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.errors import GraphInterrupt
from langgraph.graph import StateGraph
from langgraph.types import Command

from apdt.agents import AgentSet
from apdt.agents.base import spans
from apdt.agents.guard import AutonomyDenied
from apdt.services.memory_store import InMemoryEpisodeStore
from atra import contracts as c
from atra.gateway import CallContext

type Record = Callable[[str, str, c.ClinicalDecision, bool], Awaitable[c.Recommendation]]
type Node = Callable[[dict[str, Any], RunnableConfig], Awaitable[dict[str, Any]]]


def ask(kind: str, payload: dict[str, Any], allowed: list[str], role: c.Role
        ) -> dict[str, Any]:
    """The value an interrupt node hands to the human: the `c.Interrupt` fields."""
    return {"kind": kind, "payload": payload, "allowed_decisions": allowed,
            "required_role": role.value}


def decision_status(rec: c.Recommendation, decision: c.ClinicalDecision, extra: dict[str, Any]
                    ) -> dict[str, Any]:
    return {"decision": decision.decision, "recommendation_id": rec.recommendation_id,
            "status": rec.status, **extra}


class GoalOrchestrator:
    goal: ClassVar[str]

    def __init__(self, agents: AgentSet, store: InMemoryEpisodeStore, record: Record) -> None:
        self.agents = agents
        self.store = store
        self.record = record
        self.graph = self.build().compile(checkpointer=InMemorySaver())

    def build(self) -> StateGraph:
        raise NotImplementedError

    def node(self, name: str, fn: Callable[..., Awaitable[dict[str, Any]]]) -> Node:
        """`fn` wrapped in the span `apdt.node.<name>`; an interrupt is not an error."""
        async def traced(state: dict[str, Any], config: RunnableConfig) -> dict[str, Any]:
            with spans.start_as_current_span(
                    f"apdt.node.{name}", record_exception=False, set_status_on_exception=False,
                    attributes={"apdt.goal": self.goal, "apdt.run_id": state["run_id"]}) as span:
                try:
                    return await fn(state, config)
                except GraphInterrupt:
                    span.set_attribute("apdt.interrupted", True)
                    raise
        return traced

    @staticmethod
    def scope(config: Any) -> tuple[c.Episode, CallContext]:
        conf = config["configurable"]
        return conf["ep"], conf["ctx"]

    def settle(self, run_id: str) -> None:
        """Hook for state kept outside the graph once a run has ended."""

    async def start(self, run_id: str, ep: c.Episode, ctx: CallContext) -> c.RunStatus:
        return await self._drive(run_id, {"run_id": run_id, "steps": []}, ep, ctx)

    async def resume(self, run_id: str, decision: c.ClinicalDecision, ep: c.Episode,
                     ctx: CallContext) -> c.RunStatus:
        return await self._drive(run_id, Command(resume=decision.model_dump(mode="json")),
                                 ep, ctx)

    async def _drive(self, run_id: str, graph_input: Any, ep: c.Episode,
                     ctx: CallContext) -> c.RunStatus:
        config = {"configurable": {"thread_id": run_id, "ep": ep, "ctx": ctx}}
        with spans.start_as_current_span(
                "apdt.run", attributes={"apdt.goal": self.goal, "apdt.run_id": run_id}):
            try:
                out = await self.graph.ainvoke(graph_input, config)
            except AutonomyDenied as exc:
                self.settle(run_id)
                return c.RunStatus(run_id=run_id, status="failed",
                                   result={"error": str(exc), "denied": True})
        steps = out.get("steps", [])
        if out.get("__interrupt__"):
            return c.RunStatus(run_id=run_id, status="waiting_for_human",
                               interrupt=c.Interrupt.model_validate(out["__interrupt__"][0].value),
                               result={"steps": steps})
        self.settle(run_id)
        if out.get("error"):
            return c.RunStatus(run_id=run_id, status="failed",
                               result={"error": out["error"], "steps": steps})
        return c.RunStatus(run_id=run_id, status="done", result={**out["result"], "steps": steps})
