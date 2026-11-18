"""Goal checks of the standing goals (design 04, 4.9.2).

A check reads evidence the workers collected and returns `met`, `unmet` or `not_evaluated`.
`not_evaluated` is the answer whenever the check has no implementation, a kb threshold is
unset, or the person has no observations to base a model output on. It is never a pass.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

from atra import contracts as c
from atra.kb import KBError, KnowledgeBase

# A model output counts as evidence only when the person has an observation of the twin's
# fields within this window. An implementation setting, not a clinical value.
EVIDENCE_WINDOW = timedelta(days=7)

type Status = Literal["met", "unmet", "not_evaluated"]


@dataclass
class Evidence:
    """What the workers found for one twin."""

    now: datetime
    state: Mapping[str, Any] | None = None
    last_seen: Mapping[str, datetime | None] = field(default_factory=dict)
    codeless: frozenset[str] = frozenset()
    forecasts: Mapping[tuple[str, float], Mapping[str, Any]] = field(default_factory=dict)
    forecast_errors: Mapping[tuple[str, float], str] = field(default_factory=dict)

    @property
    def observed(self) -> bool:
        return any(t is not None for t in self.last_seen.values())


@dataclass
class GoalResult:
    goal_id: str
    text: str
    kind: str
    status: Status
    detail: str
    priority: int = 3
    evidence: dict[str, Any] = field(default_factory=dict)
    risk: float | None = None

    def dump(self) -> dict[str, Any]:
        return {"goal_id": self.goal_id, "text": self.text, "kind": self.kind,
                "status": self.status, "detail": self.detail, "priority": self.priority,
                "evidence": self.evidence, "risk": self.risk}


def forecast_request(goal: c.StandingGoal) -> tuple[str, float] | None:
    """The (variable, horizon_h) the check needs forecast, when it is a forecast check."""
    p = goal.check.params
    if goal.check.kind == "threshold" and "variable" in p and "horizon_h" in p:
        return str(p["variable"]), float(p["horizon_h"])
    return None


class GoalEvaluator:
    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb

    def bounds(self, goal: c.StandingGoal, override: Mapping[str, Any] | None
               ) -> tuple[dict[str, float | None], list[dict[str, Any]]]:
        """The threshold values of a goal and the kb entries they come from."""
        params = {k: goal.check.params.get(k) for k in ("above", "below", "at_least")
                  if k in goal.check.params}
        values: dict[str, float | None] = {}
        sources: list[dict[str, Any]] = []
        for key, raw in params.items():
            value = raw
            if isinstance(raw, Mapping) and "kb" in raw:
                entry_id = str(raw["kb"])
                try:
                    value = self.kb.resolve(entry_id)
                    prov = self.kb.entry(entry_id).provenance
                    sources.append({"kb": entry_id, "assumption": prov.assumption,
                                    "justification": prov.justification,
                                    "citations": [x.model_dump(exclude_none=True)
                                                  for x in prov.citations()]})
                except KBError:
                    value = None
            values[key] = value if isinstance(value, int | float) else None
        for key, raw in (override or {}).items():
            if key in ("above", "below", "at_least"):
                values[key] = raw
            elif key == "sources":
                sources = list(raw)
        return values, sources

    def evaluate(self, goal: c.StandingGoal, ev: Evidence, *,
                 override: Mapping[str, Any] | None = None) -> GoalResult:
        kind = goal.check.kind
        base: dict[str, Any] = {"goal_id": goal.id, "text": goal.text, "kind": kind,
                                "priority": goal.priority}
        if kind == "freshness":
            return self._freshness(goal, ev, base)
        if kind == "threshold":
            return self._threshold(goal, ev, base, override)
        reason = {"model_flag": "no model flag check is implemented for this goal",
                  "human_decision": "this goal needs a clinician's decision",
                  "composite": "no composite check is implemented"}[kind]
        return GoalResult(**base, status="not_evaluated", detail=reason)

    def _freshness(self, goal: c.StandingGoal, ev: Evidence, base: Mapping[str, Any]
                   ) -> GoalResult:
        fields = list(goal.check.params.get("fields", ()))
        max_age = timedelta(seconds=float(goal.check.params.get("max_age_s", 0)))
        if not fields or max_age <= timedelta(0):
            return GoalResult(**base, status="not_evaluated",
                              detail="the check names no fields or no maximum age")
        uncoded = [f for f in fields if f in ev.codeless]
        if uncoded:
            return GoalResult(**base, status="not_evaluated",
                              detail=f"no observation code is defined for: {', '.join(uncoded)}")
        ages: dict[str, float | None] = {}
        stale = []
        for name in fields:
            seen = ev.last_seen.get(name)
            ages[name] = None if seen is None else (ev.now - seen).total_seconds()
            if seen is None or ev.now - seen > max_age:
                stale.append(name)
        evidence = {"max_age_s": max_age.total_seconds(), "age_s": ages}
        if stale:
            return GoalResult(**base, status="unmet", evidence=evidence,
                              detail=f"no recent observation of: {', '.join(stale)}")
        return GoalResult(**base, status="met", evidence=evidence,
                          detail="every field was observed within the maximum age")

    def _threshold(self, goal: c.StandingGoal, ev: Evidence, base: Mapping[str, Any],
                   override: Mapping[str, Any] | None) -> GoalResult:
        p = goal.check.params
        bounds, sources = self.bounds(goal, override)
        set_bounds = {k: v for k, v in bounds.items() if v is not None}
        if not set_bounds:
            return GoalResult(**base, status="not_evaluated", evidence={"sources": sources},
                              detail="the kb holds no value for this threshold")
        if not ev.observed:
            return GoalResult(**base, status="not_evaluated", evidence={"sources": sources},
                              detail="the person has no recent observations behind this output")
        request = forecast_request(goal)
        if request is not None:
            series = ev.forecasts.get(request)
            if series is None:
                why = ev.forecast_errors.get(request, "no forecast was produced")
                return GoalResult(**base, status="not_evaluated", detail=why,
                                  evidence={"sources": sources})
            low, high = min(series["mean"]), max(series["mean"])
            where = f"forecast of {request[0]} over {request[1]:g} h"
            output_id = series.get("output_id")
        elif "field" in p:
            value = (ev.state or {}).get("state", {}).get(str(p["field"]))
            if not isinstance(value, int | float):
                return GoalResult(**base, status="not_evaluated", evidence={"sources": sources},
                                  detail=f"the state holds no value for {p['field']}")
            low = high = float(value)
            where = f"state field {p['field']}"
            output_id = (ev.state or {}).get("output_id")
        else:
            return GoalResult(**base, status="not_evaluated", evidence={"sources": sources},
                              detail="the check names neither a field nor a forecast variable")
        breaches = []
        if bounds.get("above") is not None and high > bounds["above"]:
            breaches.append(f"{high:.4g} is above {bounds['above']:g}")
        if bounds.get("below") is not None and low < bounds["below"]:
            breaches.append(f"{low:.4g} is below {bounds['below']:g}")
        if bounds.get("at_least") is not None and high >= bounds["at_least"]:
            breaches.append(f"{high:.4g} is at least {bounds['at_least']:g}")
        evidence = {"range": [low, high], "bounds": set_bounds, "sources": sources,
                    "output_id": output_id}
        if breaches:
            return GoalResult(**base, status="unmet", evidence=evidence,
                              detail=f"{where}: {'; '.join(breaches)}")
        return GoalResult(**base, status="met", evidence=evidence,
                          detail=f"{where} stays within its limits")
