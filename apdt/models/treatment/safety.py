"""Interaction and safety checks (design 05, 5.5.2) from `kb/interactions.yaml`.

A hit becomes a FHIR `DetectedIssue` and a pharmacist queue item. An issue of severity `high`
blocks signing until the pharmacist resolves it. Checks: drug-drug, drug-condition (pregnancy,
renal, hepatic, age and listed conditions), drug-food, drug-allergy by exact name, duplication
within an ATC level 4 group, and dose range against the kb targets.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from apdt.models.context import Patient, kb

CHECK_SYSTEM = "urn:atra:safety-check"
ISSUE_SEVERITY = {"high", "moderate", "low"}
_EGFR = re.compile(r"egfr_below_(\d+)$")
_AGE_OLDER = re.compile(r"age_(\d+)_or_older$")
_AGE_BELOW = re.compile(r"age_below_(\d+)$")


def components(name: str) -> frozenset[str]:
    return frozenset(part.strip().lower() for part in name.split("+") if part.strip())


@dataclass(frozen=True)
class Drug:
    name: str
    components: frozenset[str]
    atc: str | None


def drugs_of(dose_entries: Iterable[Mapping[str, Any]]) -> list[Drug]:
    return [Drug(str(d["drug"]), components(str(d["drug"])), d.get("atc"))
            for d in dose_entries if "drug" in d]


@dataclass(frozen=True)
class Issue:
    check: str
    severity: str
    ix_id: str | None
    summary: str
    management: str | None
    implicated: tuple[str, ...]
    detected_issue: dict[str, Any]

    @property
    def blocks_signing(self) -> bool:
        return self.severity == "high"

    @property
    def queue(self) -> str:
        return "pharmacist"


def detected_issue(check: str, severity: str, summary: str, management: str | None,
                   implicated: Sequence[str], kb_id: str | None, hdt_id: str | None
                   ) -> dict[str, Any]:
    resource: dict[str, Any] = {
        "resourceType": "DetectedIssue", "status": "preliminary", "severity": severity,
        "code": {"coding": [{"system": CHECK_SYSTEM, "code": check}], "text": summary},
        "identifiedDateTime": datetime.now(UTC).isoformat(),
        "detail": summary + (f" {management}" if management else ""),
        "implicated": [{"display": name} for name in implicated],
    }
    if hdt_id:
        resource["patient"] = {"reference": f"Patient/{hdt_id}"}
    if kb_id:
        resource["reference"] = f"urn:atra:kb:{kb_id}"
    if management:
        resource["mitigation"] = [{"action": {"text": management}}]
    return resource


def condition_tokens(p: Patient, egfr: float | None = None) -> set[str]:
    """The kb condition tokens that hold for the patient."""
    tokens = set(p.conditions) | set(p.flags)
    if p.pregnancy != "none":
        tokens |= {"pregnancy", f"pregnancy.{p.pregnancy}"}
    return tokens


def token_holds(token: str, p: Patient, tokens: set[str]) -> bool:
    if token in tokens:
        return True
    if (m := _EGFR.match(token)) and p.egfr is not None:
        return p.egfr < float(m.group(1))
    if m := _AGE_OLDER.match(token):
        return p.age_years >= float(m.group(1))
    if m := _AGE_BELOW.match(token):
        return p.age_years < float(m.group(1))
    return False


def _classes(entry: Mapping[str, Any]) -> list[str]:
    raw = entry.get("atc_class") or []
    return [raw] if isinstance(raw, str) else list(raw)


def check_interactions(proposed: Sequence[Drug], p: Patient, hdt_id: str | None = None
                       ) -> list[Issue]:
    """Interactions that involve a proposed drug."""
    current: set[str] = set()
    for name in p.medications:
        current |= components(name)
    new: set[str] = set()
    for d in proposed:
        new |= d.components
    union = current | new
    atcs = [d.atc for d in proposed if d.atc]
    tokens = condition_tokens(p)
    issues: list[Issue] = []
    for ix_id in kb().ids():
        if not ix_id.startswith("ix."):
            continue
        e = kb().entry(ix_id).content()
        a = components(str(e["a"]))
        a_proposed = a <= new or any(atc.startswith(c) for atc in atcs for c in _classes(e))
        kind = e["kind"]
        if kind == "drug_drug":
            raw_b = e["b"]
            alternatives = [components(str(x)) for x in (raw_b if isinstance(raw_b, list)
                                                         else [raw_b])]
            hit = next((b for b in alternatives
                        if a <= union and b <= union and (a & new or b & new)), None)
            if hit is None:
                continue
            matched = sorted(hit)
        elif kind == "drug_condition":
            raw_b = e["b"]
            targets = raw_b if isinstance(raw_b, list) else [raw_b]
            matched = [str(t) for t in targets if token_holds(str(t), p, tokens)]
            if not a_proposed or not matched:
                continue
        elif kind == "drug_food":
            if not a_proposed or str(e["b"]) not in tokens:
                continue
            matched = [str(e["b"])]
        else:
            continue
        sev = str(e["severity"])
        names = sorted(a & union) or [str(e["a"])]
        issues.append(Issue(kind, sev, ix_id, str(e["effect"]), e.get("management"),
                            tuple(names + matched),
                            detected_issue(kind, sev, str(e["effect"]), e.get("management"),
                                           names + matched, ix_id, hdt_id)))
    return issues


def check_allergies(proposed: Sequence[Drug], p: Patient, hdt_id: str | None = None
                    ) -> list[Issue]:
    allergies = {a.strip().lower() for a in p.allergies}
    out = []
    for d in proposed:
        hit = d.components & allergies
        if hit or d.name.lower() in allergies:
            summary = f"Recorded allergy to {', '.join(sorted(hit)) or d.name}."
            out.append(Issue("drug_allergy", "high", None, summary,
                             "Do not give; choose another option.", (d.name,),
                             detected_issue("drug_allergy", "high", summary,
                                            "Do not give; choose another option.", [d.name],
                                            None, hdt_id)))
    return out


def check_duplication(proposed: Sequence[Drug], current: Sequence[Drug],
                      hdt_id: str | None = None) -> list[Issue]:
    out = []
    seen: dict[str, str] = {}
    for d in [*current, *proposed]:
        if not d.atc or len(d.atc) < 5:
            continue
        group = d.atc[:5]
        if group in seen and seen[group] != d.name and \
                any(d.name == q.name for q in proposed):
            summary = f"{d.name} and {seen[group]} are in the same ATC group {group}."
            out.append(Issue("duplication", "moderate", None, summary,
                             "Confirm that both are needed.", (d.name, seen[group]),
                             detected_issue("duplication", "moderate", summary,
                                            "Confirm that both are needed.",
                                            [d.name, seen[group]], None, hdt_id)))
        seen.setdefault(group, d.name)
    return out


def check_dose_range(dose_entry: Mapping[str, Any], mg_per_dose: Mapping[str, float],
                     weight_kg: float | None, hdt_id: str | None = None) -> list[Issue]:
    """Compare a computed dose with the kb target range per kg."""
    if not weight_kg:
        return []
    out = []
    per_day = dose_entry.get("target_mg_per_kg_per_day")
    total = dose_entry.get("target_total_mg_per_kg")
    for component, (lo, hi) in {**(per_day or {}), **(total or {})}.items():
        if component not in mg_per_dose:
            continue
        doses = float(dose_entry.get("doses_per_day", 1))
        mg = mg_per_dose[component] * doses
        value = mg / weight_kg
        if total and component in total:
            value = mg_per_dose[component] * doses * float(dose_entry["duration_days"]) / weight_kg
        if not float(lo) <= value <= float(hi):
            summary = (f"{component} dose of {value:.1f} mg/kg is outside the kb target range "
                       f"{lo} to {hi} mg/kg.")
            out.append(Issue("dose_range", "moderate", None, summary, "Review the dose.",
                             (component,), detected_issue("dose_range", "moderate", summary,
                                                          "Review the dose.", [component], None,
                                                          hdt_id)))
    return out
