"""Capacity and proxy logic (design 05, 5.5.4) from `kb/capacity.yaml`.

The kb rules run in the JSON rule engine. The first rule that holds decides who acts for the
patient. The decision carries the rule and its checks so that every proxy decision is audited
with the rule that allowed it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apdt.models.context import kb
from atra.rules import Rule, RuleEngine

ENTRY = "capacity.rules"


@dataclass(frozen=True)
class CapacityDecision:
    actor: str
    proxy_relationship: str
    rule_id: str
    escalate: bool
    audit: dict[str, Any]


def _resolve(ref: str) -> Any:
    return kb().lookup(ENTRY, ref)


def _rules() -> list[Rule]:
    spec = kb().entry(ENTRY).content()["rules"]
    out = []
    for position, r in enumerate(spec):
        when = r["when"]
        leaves: list[dict[str, Any]] = []
        for key, value in when.items():
            if key == "age_below_years":
                leaves.append({"fact": "age_years", "op": "lt", "value": {
                    "kb": f"rules[id={r['id']}].when.age_below_years"}})
            elif key == "avpu_not":
                leaves.append({"fact": "avpu", "op": "ne", "value": str(value)})
            elif key == "capacity_assessment":
                leaves.append({"fact": "capacity_assessment", "op": "eq", "value": str(value)})
            else:
                raise ValueError(f"capacity rule {r['id']}: unknown condition {key}")
        out.append(Rule.from_dict({
            "id": r["id"], "source": f"kb:{ENTRY}", "when": {"all": leaves},
            "then": {"actor": r["actor"], "proxy_relationship": r.get("proxy_relationship"),
                     "rule": r["id"]},
            "priority": len(spec) - position}))
    return out


def decide(age_years: float, avpu: str = "A", capacity_assessment: str | None = None,
           *, has_registered_proxy: bool = False) -> CapacityDecision:
    """Who gives consent and decides for the patient."""
    facts: dict[str, Any] = {"age_years": age_years, "avpu": avpu}
    if capacity_assessment is not None:
        facts["capacity_assessment"] = capacity_assessment
    result = RuleEngine(_rules(), _resolve).evaluate(facts, first_match=True)
    out = result.outcome
    escalate = out["actor"] != "self" and not has_registered_proxy \
        and kb().entry(ENTRY).content()["no_registered_proxy"] == "escalate_to_clinician"
    audit = {"rule": out["rule"], "facts": facts, "checks": [
        c for step in result.trace for c in step.checks], "kb": ENTRY,
        "proxy_scope": kb().entry(ENTRY).content()["proxy_scope"]}
    return CapacityDecision(out["actor"], str(out["proxy_relationship"]), out["rule"],
                            escalate, audit)
