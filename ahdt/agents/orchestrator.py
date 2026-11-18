"""TwinOrchestrator (design 04, 4.9.2): one LangGraph per twin, configured from its standing goals.

The graph runs `sense, update_state, assess_goals, plan, act, explain, report`. Workers do the
tool calls; the orchestrator holds the goals, decides the steps and builds the report.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from ahdt.agents.goalchecks import (
    EVIDENCE_WINDOW,
    Evidence,
    GoalEvaluator,
    GoalResult,
    forecast_request,
)
from ahdt.agents.guard import ActionDenied, ProposedAction
from ahdt.agents.toolbox import ToolBox
from ahdt.agents.workers import (
    AnomalyAgent,
    ExplanationAgent,
    ForecastingAgent,
    MonitoringAgent,
    RecommendationAgent,
    WorkerOutput,
)
from atra import contracts as c
from atra.connectors import DTKind
from atra.gateway import CallContext
from atra.kb import KnowledgeBase


class RunState(TypedDict, total=False):
    ctx: CallContext
    now: datetime
    overrides: Mapping[str, Mapping[str, Any]]
    triggers: Sequence[str]
    probes: Sequence[str]
    evidence: Evidence
    severity: str | None
    state_output_id: str | None
    results: list[GoalResult]
    steps: list[dict[str, Any]]
    planned: list[dict[str, Any]]
    calls: list[c.ToolCallRecord]
    denials: list[dict[str, str]]
    proposals: list[c.Recommendation]
    explanations: list[str]
    missing: list[str]
    failed: bool
    paused: bool
    report: dict[str, Any]


@dataclass
class OrchestratorRun:
    result: c.AgentResult
    report: dict[str, Any]


class TwinOrchestrator:
    tier = "7.2"

    def __init__(self, definition: c.TwinDefinition, toolbox: ToolBox, kb: KnowledgeBase) -> None:
        self.twin: DTKind = definition.kind
        self.definition = definition
        self.name = f"orchestrator-{definition.kind.value}"
        self.toolbox = toolbox
        self.evaluator = GoalEvaluator(kb)
        self.monitoring = MonitoringAgent(self.twin, toolbox)
        self.anomaly = AnomalyAgent(self.twin, toolbox)
        self.forecasting = ForecastingAgent(self.twin, toolbox)
        self.explanation = ExplanationAgent(self.twin, toolbox)
        self.recommendation = RecommendationAgent(self.twin, toolbox, kb)
        self.workers = (self.monitoring, self.anomaly, self.forecasting, self.explanation,
                        self.recommendation)
        self.tools = frozenset().union(*(w.tools for w in self.workers))
        self.goal = c.Goal(
            goal_id=f"{self.twin.value}.standing", owner="twin", priority=3,
            text=f"Meet the standing goals of the {self.twin.value.replace('_', ' ')} twin",
            check=c.GoalCheck(kind="composite",
                              params={"goals": [g.id for g in definition.standing_goals]}))
        self.paused = False
        self.pause_reason: str | None = None
        self.last_report: dict[str, Any] | None = None
        self._graph = self._build()

    # ------------------------------------------------------------------ Orchestrator protocol

    async def act(self, goal: c.Goal, ctx: CallContext) -> c.AgentResult:
        return (await self.run(ctx)).result

    def plan(self, state: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Steps for the unmet goals: one explanation per distinct output, then a lookup of
        support actions when a trigger or an unmet goal calls for one."""
        results: list[GoalResult] = state.get("results", [])
        unmet = [r for r in results if r.status == "unmet"]
        steps: list[dict[str, Any]] = []
        outputs: list[str] = []
        if state.get("severity") in ("watch", "alert") and state.get("state_output_id"):
            outputs.append(str(state["state_output_id"]))
        outputs += [str(r.evidence["output_id"]) for r in unmet if r.evidence.get("output_id")]
        for output_id in dict.fromkeys(outputs):
            steps.append({"step": "explain", "output_id": output_id})
        triggers = list(state.get("triggers", ()))
        if unmet or triggers:
            steps.append({"step": "recommend", "triggers": triggers,
                          "goals": [r.goal_id for r in unmet]})
        return steps

    async def delegate(self, step: Mapping[str, Any], ctx: CallContext) -> c.AgentResult:
        if step["step"] == "explain":
            out = await self.explanation.run(self.goal, ctx, output_id=step["output_id"])
        else:
            out = await self.recommendation.run(self.goal, ctx, triggers=step["triggers"])
        return out.result

    def report(self, state: Mapping[str, Any]) -> dict[str, Any]:
        results: list[GoalResult] = state.get("results", [])
        counts = {s: sum(r.status == s for r in results)
                  for s in ("met", "unmet", "not_evaluated")}
        return {
            "twin": self.twin.value, "orchestrator": self.name,
            "hdt_id": state["ctx"].hdt_id, "as_of": state["now"].isoformat(),
            "paused": state.get("paused", False), "severity": state.get("severity"),
            "goals": [r.dump() for r in results], "summary": counts,
            "steps": state.get("steps", []),
            "tool_calls": [t.model_dump() for t in state.get("calls", [])],
            "proposals": [p.model_dump(mode="json") for p in state.get("proposals", [])],
            "explanations": state.get("explanations", []),
            "denials": state.get("denials", []),
            "missing_evidence": state.get("missing", []),
        }

    # ------------------------------------------------------------------ run

    async def run(self, ctx: CallContext, *, now: datetime | None = None,
                  overrides: Mapping[str, Mapping[str, Any]] | None = None,
                  triggers: Sequence[str] = (), probes: Sequence[str] = ()) -> OrchestratorRun:
        start: RunState = {
            "ctx": ctx, "now": now or datetime.now(UTC), "overrides": overrides or {},
            "triggers": list(triggers), "probes": list(probes), "results": [], "steps": [],
            "calls": [], "denials": [], "proposals": [], "explanations": [], "missing": [],
            "failed": False, "paused": self.paused}
        final: RunState
        if self.paused:
            start["missing"] = [f"{self.name} is paused: {self.pause_reason or 'no reason given'}"]
            start["report"] = self.report(start)
            final = start
        else:
            final = await self._graph.ainvoke(start)
        self.last_report = final["report"]
        degraded = final["failed"] or final["paused"]
        result = c.AgentResult(
            agent=self.name, goal_id=self.goal.goal_id, proposals=final["proposals"],
            tool_calls=final["calls"], explanations=final["explanations"],
            autonomy_level=c.AutonomyLevel.RECOMMEND,
            status="failed" if final["paused"] else "degraded" if degraded else "ok",
            missing_evidence=final["missing"])
        return OrchestratorRun(result, final["report"])

    # ------------------------------------------------------------------ graph

    def _build(self) -> Any:
        graph = StateGraph(RunState)
        for name, node in (("sense", self._sense), ("update_state", self._update_state),
                           ("assess_goals", self._assess), ("plan", self._plan),
                           ("act", self._act), ("explain", self._explain),
                           ("report", self._report)):
            graph.add_node(name, node)
        graph.add_edge(START, "sense")
        for a, b in (("sense", "update_state"), ("update_state", "assess_goals"),
                     ("assess_goals", "plan"), ("plan", "act"), ("act", "explain"),
                     ("explain", "report")):
            graph.add_edge(a, b)
        graph.add_edge("report", END)
        return graph.compile()

    def _record(self, s: RunState, node: str, out: WorkerOutput, **extra: Any) -> None:
        s["steps"].append({"node": node, "agent": out.result.agent, "status": out.result.status,
                           "tools": [t.tool for t in out.result.tool_calls], **extra})
        s["calls"].extend(out.result.tool_calls)
        s["denials"].extend(out.denials)
        s["missing"].extend(out.result.missing_evidence)
        s["failed"] = s["failed"] or out.result.status == "failed"

    def _fields(self) -> tuple[dict[str, str], frozenset[str]]:
        coded = {f.name: f.loinc for f in self.definition.fields if f.loinc}
        codeless = frozenset(f.name for f in self.definition.fields if not f.loinc)
        return coded, codeless

    async def _sense(self, s: RunState) -> dict[str, Any]:
        coded, codeless = self._fields()
        ages = [float(g.check.params.get("max_age_s", 0)) for g in self.definition.standing_goals
                if g.check.kind == "freshness"]
        lookback = max([EVIDENCE_WINDOW.total_seconds(), *ages])
        out = await self.monitoring.run(self.goal, s["ctx"], fields=coded, now=s["now"],
                                        lookback_s=lookback)
        self._record(s, "sense", out)
        seen = {k: datetime.fromisoformat(v) if isinstance(v, str) else v
                for k, v in out.data.get("last_seen", {}).items()}
        state = out.data.get("state")
        s["evidence"] = Evidence(now=s["now"], state=state, last_seen=seen, codeless=codeless)
        return {"evidence": s["evidence"], "state_output_id": (state or {}).get("output_id"),
                **self._carry(s)}

    async def _update_state(self, s: RunState) -> dict[str, Any]:
        state = s["evidence"].state
        if state is None:
            return {}
        out = await self.anomaly.run(self.goal, s["ctx"], state=state)
        self._record(s, "update_state", out, severity=out.data.get("severity"))
        return {"severity": out.data.get("severity"), **self._carry(s)}

    async def _assess(self, s: RunState) -> dict[str, Any]:
        ev = s["evidence"]
        forecasts: dict[tuple[str, float], Mapping[str, Any]] = {}
        errors: dict[tuple[str, float], str] = {}
        for goal in self.definition.standing_goals:
            request = forecast_request(goal)
            if request is None or request in forecasts or request in errors:
                continue
            bounds, _ = self.evaluator.bounds(goal, s["overrides"].get(goal.id))
            if not ev.observed or all(v is None for v in bounds.values()):
                continue
            out = await self.forecasting.run(self.goal, s["ctx"], variable=request[0],
                                             horizon_h=request[1])
            self._record(s, "assess_goals", out, goal_id=goal.id)
            if out.result.status == "ok" and out.data:
                forecasts[request] = out.data
            else:
                errors[request] = "; ".join(out.result.missing_evidence) or "forecast failed"
        ev.forecasts, ev.forecast_errors = forecasts, errors
        results = [self.evaluator.evaluate(g, ev, override=s["overrides"].get(g.id))
                   for g in self.definition.standing_goals]
        return {"results": results, **self._carry(s)}

    async def _plan(self, s: RunState) -> dict[str, Any]:
        steps = self.plan(s)
        s["steps"].append({"node": "plan", "agent": self.name, "status": "ok",
                           "tools": [], "planned": [x["step"] for x in steps]})
        return {"planned": steps, **self._carry(s)}

    async def _act(self, s: RunState) -> dict[str, Any]:
        proposals = list(s["proposals"])
        for step in s["planned"]:
            if step["step"] != "recommend":
                continue
            out = await self.recommendation.run(self.goal, s["ctx"], triggers=step["triggers"])
            self._record(s, "act", out, proposed=len(out.result.proposals))
            proposals += out.result.proposals
        for action_class in s["probes"]:
            self._probe(s, action_class)
        return {"proposals": proposals, **self._carry(s)}

    def _probe(self, s: RunState, action_class: str) -> None:
        """Attempt `action_class` at the `act` level, to show what the guard decides."""
        action = ProposedAction(agent=self.name, action_class=action_class,
                                mode=c.AutonomyLevel.ACT, hdt_id=s["ctx"].hdt_id,
                                target="probe")
        try:
            self.toolbox.guard.authorise(action, s["ctx"])
            s["steps"].append({"node": "act", "agent": self.name, "status": "ok",
                               "tools": [], "probe": action_class, "outcome": "allowed"})
        except ActionDenied as denied:
            s["denials"].append({"agent": self.name, "action": action_class,
                                 "reason": denied.reason})
            s["steps"].append({"node": "act", "agent": self.name, "status": "ok",
                               "tools": [], "probe": action_class, "outcome": "denied"})

    async def _explain(self, s: RunState) -> dict[str, Any]:
        explanations = list(s["explanations"])
        for step in s["planned"]:
            if step["step"] != "explain":
                continue
            out = await self.explanation.run(self.goal, s["ctx"], output_id=step["output_id"])
            self._record(s, "explain", out, output_id=step["output_id"])
            explanations += out.result.explanations
        return {"explanations": explanations, **self._carry(s)}

    async def _report(self, s: RunState) -> dict[str, Any]:
        s["steps"].append({"node": "report", "agent": self.name, "status": "ok", "tools": []})
        return {"report": self.report(s), **self._carry(s)}

    @staticmethod
    def _carry(s: RunState) -> dict[str, Any]:
        return {k: s[k] for k in ("steps", "calls", "denials", "missing", "failed")}  # type: ignore[literal-required]
