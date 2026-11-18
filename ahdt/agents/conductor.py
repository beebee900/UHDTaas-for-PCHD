"""HDT conductor (design 04, 4.9.3): goal decomposition, arbitration, escalation, pausing."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ahdt.agents.guard import ActionDenied, ProposedAction, SafetyGuard
from ahdt.agents.orchestrator import TwinOrchestrator
from atra import contracts as c
from atra.connectors import DTKind
from atra.gateway import CallContext
from atra.ids import new_record_id
from atra.kb import KnowledgeBase

NAME = "ahdt-conductor"
TEMPLATE_PREFIX = "goal_template."
TIE_NOTE = "tie resolved by the lower risk plan; NSGA-II over risk, benefit and burden is deferred"


@dataclass(frozen=True)
class Plan:
    """A candidate plan from one twin. `risk_to` is the risk the plan puts on other twins."""

    plan_id: str
    twin: str
    action: str
    risk: float = 0.0
    risk_to: Mapping[str, float] = field(default_factory=dict)

    @classmethod
    def of(cls, raw: Mapping[str, Any]) -> Plan:
        return cls(str(raw["plan_id"]), str(raw["twin"]), str(raw["action"]),
                   float(raw.get("risk", 0.0)), dict(raw.get("risk_to", {})))

    @property
    def worst_risk(self) -> float:
        return max([self.risk, *self.risk_to.values()])


@dataclass
class Arbitration:
    chosen: str | None
    rule: str
    ranking: list[str]
    excluded: list[dict[str, str]]
    notes: list[str]

    def dump(self) -> dict[str, Any]:
        return {"chosen": self.chosen, "rule": self.rule, "ranking": self.ranking,
                "excluded": self.excluded, "notes": self.notes}


class Conductor:
    tier = "7.3"
    name = NAME
    twin = "apdt"
    tools: frozenset[str] = frozenset()

    def __init__(self, orchestrator_of: Callable[[DTKind], TwinOrchestrator | None],
                 guard: SafetyGuard, kb: KnowledgeBase, runtime: Any) -> None:
        self.orchestrator_of = orchestrator_of
        self.guard = guard
        self.kb = kb
        self.runtime = runtime
        self.metrics: dict[str, dict[str, int]] = {}
        priority = kb.entry("arbitration.priority").content()
        self.order: list[str] = list(priority["order"])
        self.twin_class: Mapping[str, str] = priority["twin_class"]
        self.escalation_risk = float(kb.resolve("conductor.escalation_risk"))
        self.last_status: dict[str, Any] = {}

    # ------------------------------------------------------------------ arbitration

    def rank(self, twin: str) -> int:
        cls = self.twin_class.get(twin)
        return self.order.index(cls) if cls in self.order else len(self.order)

    def arbitrate(self, plans: Sequence[Plan | Mapping[str, Any]]) -> Arbitration:
        """Choose one of several conflicting plans.

        A plan that puts a risk at or above the escalation limit on a twin of higher priority
        is excluded. Of the rest, the plan of the highest-priority twin wins. Plans of equal
        priority are separated by the lower worst-case risk."""
        candidates = [p if isinstance(p, Plan) else Plan.of(p) for p in plans]
        excluded: list[dict[str, str]] = []
        safe: list[Plan] = []
        for p in candidates:
            harmed = [t for t, r in p.risk_to.items()
                      if r >= self.escalation_risk and self.rank(t) < self.rank(p.twin)]
            if harmed:
                excluded.append({"plan_id": p.plan_id,
                                 "reason": f"risk to higher-priority twin: {', '.join(harmed)}"})
            else:
                safe.append(p)
        if not safe:
            return Arbitration(None, "no safe plan", [], excluded,
                               ["every plan puts a high risk on a higher-priority twin"])
        ranked = sorted(safe, key=lambda p: (self.rank(p.twin), p.worst_risk, p.plan_id))
        best = ranked[0]
        tied = [p for p in ranked if self.rank(p.twin) == self.rank(best.twin)]
        notes: list[str] = []
        rule = "fixed clinical priority" if len(candidates) > 1 else "single plan"
        if len(tied) > 1:
            rule = "lower risk"
            notes.append(TIE_NOTE)
        return Arbitration(best.plan_id, rule, [p.plan_id for p in ranked], excluded, notes)

    # ------------------------------------------------------------------ decomposition

    def template_for(self, person_goal: str) -> tuple[str, Mapping[str, Any]] | None:
        wanted = " ".join(person_goal.lower().split())
        for entry_id in self.kb.ids():
            if not entry_id.startswith(TEMPLATE_PREFIX):
                continue
            content = self.kb.entry(entry_id).content()
            if wanted in (entry_id.lower(), " ".join(str(content["person_goal"]).lower().split())):
                return entry_id, content
        return None

    def _override(self, sub_goal: Mapping[str, Any]) -> dict[str, Any]:
        override: dict[str, Any] = {}
        sources: list[dict[str, Any]] = []
        for key, ref in (sub_goal.get("set") or {}).items():
            override[key] = self.kb.lookup(ref["threshold"], ref["path"])
            prov = self.kb.entry(ref["threshold"]).provenance
            sources.append({"kb": ref["threshold"], "path": ref["path"],
                            "assumption": prov.assumption,
                            "citations": [x.model_dump(exclude_none=True)
                                          for x in prov.citations()]})
        if sources:
            override["sources"] = sources
        return override

    async def submit_goal(self, person_goal: str, ctx: CallContext, *,
                          now: datetime | None = None,
                          plans: Sequence[Plan | Mapping[str, Any]] = (),
                          probes: Sequence[str] = ()) -> dict[str, Any]:
        found = self.template_for(person_goal)
        report: dict[str, Any] = {
            "conductor": NAME, "hdt_id": ctx.hdt_id, "person_goal": person_goal,
            "template": found[0] if found else None, "sub_goals": [], "orchestrators": {},
            "arbitration": None, "escalations": [], "denials": [], "paused": [], "notes": []}
        if found is None:
            report["status"] = "unmatched"
            report["notes"].append("no goal template matches; the LLM fallback is deferred")
            self.last_status[ctx.hdt_id] = report
            return report
        template = found[1]
        by_twin: dict[DTKind, dict[str, dict[str, Any]]] = {}
        wanted: dict[DTKind, list[Mapping[str, Any]]] = {}
        for sub in template["sub_goals"]:
            kind = DTKind(sub["twin"])
            wanted.setdefault(kind, []).append(sub)
            override = self._override(sub)
            if override:
                by_twin.setdefault(kind, {})[sub["goal"]] = override
        when = now or datetime.now(UTC)
        for kind in sorted(wanted, key=lambda k: self.rank(k.value)):
            orchestrator = self.orchestrator_of(kind)
            if orchestrator is None:
                report["notes"].append(f"no orchestrator for {kind.value}")
                continue
            if orchestrator.paused:
                report["paused"].append(orchestrator.name)
            run = await orchestrator.run(ctx, now=when, overrides=by_twin.get(kind))
            self._meter(orchestrator.name, run.result, run.report)
            report["orchestrators"][kind.value] = run.report
            report["denials"].extend(run.report["denials"])
            by_id = {g["goal_id"]: g for g in run.report["goals"]}
            for sub in wanted[kind]:
                goal = by_id.get(sub["goal"])
                report["sub_goals"].append({
                    "twin": kind.value, "goal_id": sub["goal"],
                    "status": goal["status"] if goal else "not_evaluated",
                    "detail": goal["detail"] if goal else "the orchestrator has no such goal",
                    "sources": (goal or {}).get("evidence", {}).get("sources", [])})
                if goal and goal["risk"] is not None and goal["risk"] >= self.escalation_risk:
                    report["escalations"].append(await self.escalate(
                        ctx, f"{sub['goal']} at risk {goal['risk']:.2f}", goal["risk"]))
        for action_class in probes:
            report["denials"].extend(self._probe(ctx, action_class))
        candidates = [p if isinstance(p, Plan) else Plan.of(p) for p in plans]
        if candidates:
            decision = self.arbitrate(candidates)
            report["arbitration"] = decision.dump()
            chosen = next((p for p in candidates if p.plan_id == decision.chosen), None)
            if chosen is None or decision.excluded or chosen.worst_risk >= self.escalation_risk:
                risk = chosen.worst_risk if chosen else max(p.worst_risk for p in candidates)
                report["escalations"].append(await self.escalate(
                    ctx, "arbitration needs a clinician's decision", risk))
        report["status"] = "done"
        self.last_status[ctx.hdt_id] = report
        return report

    # ------------------------------------------------------------------ escalation, pausing

    async def escalate(self, ctx: CallContext, reason: str, risk: float) -> dict[str, Any]:
        """Send a high-risk or uncertain decision to the person's clinician, by consent.
        Nothing clinical is actuated."""
        action = ProposedAction(agent=NAME, action_class="routine_action",
                                mode=c.AutonomyLevel.ACT, hdt_id=ctx.hdt_id,
                                target="escalate:clinician")
        entry: dict[str, Any] = {"to": "clinician", "reason": reason, "risk": risk,
                                 "routed": None}
        try:
            self.guard.authorise(action, ctx)
        except ActionDenied as denied:
            entry["denied"] = denied.reason
            return entry
        entry["routed"] = await self.runtime.notifier.send(
            ctx.hdt_id, "clinician", reason=reason, risk=risk, source=NAME)
        return entry

    async def pause(self, orchestrator: TwinOrchestrator, ctx: CallContext, reason: str, *,
                    by: str = NAME) -> None:
        """Pause an orchestrator. Only the conductor holds this right (autonomy.yaml)."""
        self.guard.authorise(ProposedAction(
            agent=by, action_class="pause_orchestrator", mode=c.AutonomyLevel.ACT,
            hdt_id=ctx.hdt_id, target=orchestrator.name), ctx)
        orchestrator.paused, orchestrator.pause_reason = True, reason
        await self.runtime.backends.events.publish(c.EventEnvelope(
            event_id=new_record_id(), event_type="agent.paused", source="ahdt.conductor",
            hdt_id=ctx.hdt_id, wall_time=datetime.now(UTC), sim_time=None,
            trace_id=new_record_id(), payload={"orchestrator": orchestrator.name,
                                               "reason": reason}))

    def resume(self, orchestrator: TwinOrchestrator) -> None:
        orchestrator.paused, orchestrator.pause_reason = False, None

    def _probe(self, ctx: CallContext, action_class: str) -> list[dict[str, str]]:
        try:
            self.guard.authorise(ProposedAction(
                agent=NAME, action_class=action_class, mode=c.AutonomyLevel.ACT,
                hdt_id=ctx.hdt_id, target="probe"), ctx)
        except ActionDenied as denied:
            return [{"agent": NAME, "action": action_class, "reason": denied.reason}]
        return []

    def _meter(self, name: str, result: c.AgentResult, report: Mapping[str, Any]) -> None:
        m = self.metrics.setdefault(name, {"runs": 0, "failed_runs": 0, "tool_calls": 0,
                                           "denials": 0})
        m["runs"] += 1
        m["failed_runs"] += result.status == "failed"
        m["tool_calls"] += len(result.tool_calls)
        m["denials"] += len(report["denials"])
