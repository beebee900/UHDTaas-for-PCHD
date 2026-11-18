"""Guideline-concordant treatment options (design 05, 5.5.2).

Every kb treatment entry for a condition becomes one rule of the JSON rule engine
(`atra.rules`). The rule's conditions are the entry's `eligibility`; numeric limits are kb
references, so no clinical number is written in code (rule R5). An exclusion names kb
interactions: the option is dropped when one of them is active for its regimen. The result
lists the eligible options in guideline order and the ineligible ones with the failed checks.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from apdt.models.context import Observations, Patient, kb, param
from apdt.models.treatment.dosing import Dose, adjustments, compute_dose
from apdt.models.treatment.safety import (
    Drug,
    Issue,
    check_allergies,
    check_interactions,
    drugs_of,
)
from atra.kb import Citation
from atra.rules import Rule, RuleEngine, RuleResult

PREFERENCE_ORDER = {"first_line": 0, "second_line": 1, "alternative": 2, "pre_referral": 3}


@dataclass
class Option:
    option_id: str
    condition: str
    severity: Any
    preference: str
    doses: list[Dose]
    note: str | None
    citations: list[Citation]
    issues: list[Issue] = field(default_factory=list)
    adjustments: list[dict[str, Any]] = field(default_factory=list)
    fired_rule: str = ""
    checks: list[dict[str, Any]] = field(default_factory=list)
    then: str | None = None
    empirical_allowed: bool = False
    drug_class: str | None = None
    guidance_only: bool = False
    unverified: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return any(i.blocks_signing for i in self.issues)


@dataclass
class Ineligible:
    option_id: str
    reason: str
    checks: list[dict[str, Any]]


@dataclass
class OptionSet:
    condition: str
    severity: str | None
    eligible: list[Option]
    ineligible: list[Ineligible]


def _resolve(ref: str) -> Any:
    entry_id, path = ref.split("#", 1)
    return kb().lookup(entry_id, path)


def facts_for(p: Patient, interactions: list[str]) -> dict[str, Any]:
    return {"oral_intake": p.oral_intake, "pregnancy": p.pregnancy,
            "age_years": p.age_years, "patient_group": p.patient_group,
            "intramuscular_available": p.intramuscular_available,
            "referral_possible": p.referral_possible,
            "active_interactions": interactions, **dict(p.context)}


def eligibility_rule(entry_id: str, eligibility: Mapping[str, Any], exclusions: list[str],
                     known: Mapping[str, Any]) -> tuple[Rule, list[str]]:
    """The rule of one entry, and the eligibility facts that are not known for the patient
    (those leaves are left out and reported as unverified)."""
    leaves: list[dict[str, Any]] = []
    unverified: list[str] = []
    for key, value in eligibility.items():
        fact = "age_years" if key == "age_below_years" else key
        if fact not in known:
            unverified.append(key)
        elif key == "age_below_years":
            leaves.append({"fact": "age_years", "op": "lt",
                           "value": {"kb": f"{entry_id}#eligibility.age_below_years"}})
        elif isinstance(value, list):
            leaves.append({"fact": key, "op": "in", "value": [str(v) for v in value]})
        else:
            leaves.append({"fact": key, "op": "eq", "value": value})
    for ix in exclusions:
        leaves.append({"not": {"fact": "active_interactions", "op": "contains", "value": ix}})
    rule = Rule.from_dict({"id": entry_id, "source": f"kb:{entry_id}",
                           "when": {"all": leaves}, "then": {"ok": True}})
    return rule, unverified


def _severity_matches(entry_severity: Any, graded: str | None) -> bool:
    if graded is None or entry_severity is None:
        return True
    values = entry_severity if isinstance(entry_severity, list) else [entry_severity]
    return graded in values


def grade_severity(condition: str, p: Patient, obs: Observations) -> str | None:
    """The severity label that treatment entries for the condition are keyed by, or None
    when no label can be graded."""
    content = kb().entry(condition).content()
    present = {f for f, v in obs.findings.items() if v}
    rules = param("severity_rules").get(condition, {})
    levels = content.get("severity_levels")
    if condition == "cond.hypertension":
        target = kb().lookup("tx.hypertension.targets", "target_general")
        sbp, dbp = obs.measurements.get("sbp"), obs.measurements.get("dbp")
        if (sbp is not None and sbp >= float(target["systolic_below"])) or \
                (dbp is not None and dbp >= float(target["diastolic_below"])):
            return "uncontrolled"
        return "controlled"
    if "severe_when" in rules:
        severe = (p.pregnancy != "none"
                  or {"find.shock", "find.hypotension", "find.impaired_consciousness"} & present)
        return "severe" if severe else str(rules["default"])
    red = set(content.get("red_flags", []))
    if levels and red & present:
        return str(levels[-1])
    if "default" in rules:
        return str(rules["default"])
    if levels:
        return str(levels[0])
    return None


def options_for(condition: str, p: Patient, obs: Observations, hdt_id: str | None = None
                ) -> OptionSet:
    k = kb()
    severity = grade_severity(condition, p, obs)
    eligible: list[Option] = []
    ineligible: list[Ineligible] = []
    for entry_id in k.ids():
        if not entry_id.startswith("tx."):
            continue
        e = k.entry(entry_id).content()
        if e.get("condition") != condition or "preference" not in e:
            continue
        if not _severity_matches(e.get("severity"), severity):
            continue
        regimen_ids = ([] if e.get("regimen") is None
                       else e["regimen"] if isinstance(e["regimen"], list) else [e["regimen"]])
        if not regimen_ids and not e.get("drug_class"):
            ineligible.append(Ineligible(entry_id, "no sourced regimen in the kb", []))
            continue
        doses = [compute_dose(k.entry(r).content() | {"id": r}, p, hdt_id) for r in regimen_ids]
        listed = drugs_of([d.raw for d in doses if d.raw is not None])
        issues = (check_interactions(listed, p, hdt_id) + check_allergies(listed, p, hdt_id)
                  if listed else [])
        active = [i.ix_id for i in issues if i.ix_id]
        facts = facts_for(p, active)
        rule, unverified = eligibility_rule(entry_id, e.get("eligibility", {}),
                                            list(e.get("exclusions", [])), facts)
        result: RuleResult = RuleEngine([rule], _resolve).evaluate(facts)
        checks = [c for step in result.trace for c in step.checks]
        if not result.fired:
            failed = [c["fact"] for c in checks if not c["ok"]]
            hit = [i for i in e.get("exclusions", []) if i in active]
            ineligible.append(Ineligible(entry_id, "; ".join(
                [f"fails {f}" for f in failed] + [f"excluded by {i}" for i in hit]), checks))
            continue
        first_prov = k.entry(entry_id).provenance.citations()
        eligible.append(Option(
            entry_id, condition, e.get("severity"), str(e["preference"]), doses,
            e.get("note"), first_prov, issues,
            adjustments(listed, issues, p), entry_id, checks, e.get("then"),
            bool(e.get("empirical_allowed", False)), e.get("drug_class"),
            guidance_only=not regimen_ids, unverified=unverified))
    order = {eid: i for i, eid in enumerate(k.ids())}
    eligible.sort(key=lambda o: (PREFERENCE_ORDER.get(o.preference, 9), o.blocked,
                                 order[o.option_id]))
    return OptionSet(condition, severity, eligible, ineligible)


def drugs_in(option: Option) -> list[Drug]:
    return drugs_of([d.raw for d in option.doses if d.raw is not None])
