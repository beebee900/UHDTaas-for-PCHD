"""Personalised dosing (design 05, 5.5.2) from `kb/doses/*.yaml`.

Weight bands and mg/kg doses are read from the kb entry. Dose adjustments come from active
kb interactions that carry a dose (for example dolutegravir with rifampicin) and from CPIC
pharmacogenomic entries when the patient's phenotype for the gene is known. A dose entry
shape that this module does not structure is returned unchanged with `structured=False`.
PBPK and population-PK results are added by `apdt.models.treatment.simulation`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from apdt.models.context import Patient, kb
from apdt.models.treatment.safety import Drug, Issue, check_dose_range, drugs_of

PASS_THROUGH = ("route", "doses_per_day", "every_h", "duration_days", "advice", "monitoring",
                "first_two_doses_apart_h", "total_duration_days", "then")


@dataclass
class Dose:
    dose_id: str
    drug: str
    atc: str | None
    per_dose: dict[str, Any] = field(default_factory=dict)
    schedule: dict[str, Any] = field(default_factory=dict)
    basis: str = ""
    structured: bool = True
    missing: list[str] = field(default_factory=list)
    adjustments: list[dict[str, Any]] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    raw: Mapping[str, Any] | None = None


def _in_band(band: Mapping[str, Any], weight: float) -> bool:
    return weight >= float(band.get("min_kg", 0.0)) and weight < float(band.get("below_kg",
                                                                                 float("inf")))


def _band(bands: Sequence[Mapping[str, Any]], weight: float) -> Mapping[str, Any] | None:
    return next((b for b in bands if _in_band(b, weight)), None)


def _select(entry: Mapping[str, Any], p: Patient) -> Mapping[str, Any]:
    """The adult or child block of an entry that holds both."""
    group = p.patient_group
    if group in entry and isinstance(entry[group], Mapping):
        return {**{k: v for k, v in entry.items() if k not in ("adult", "child")},
                **entry[group]}
    return entry


def _per_kg_scalar(entry: Mapping[str, Any]) -> bool:
    keys = ("mg_per_kg", "mg_per_kg_single_dose", "mg_per_kg_per_day")
    return all(isinstance(entry[k], int | float) for k in keys if k in entry)


def compute_dose(entry: Mapping[str, Any], p: Patient, hdt_id: str | None = None) -> Dose:
    entry = _select(entry, p)
    dose = Dose(str(entry["id"]), str(entry["drug"]), entry.get("atc"), raw=entry)
    dose.schedule = {k: entry[k] for k in PASS_THROUGH if k in entry}
    w = p.weight_kg
    if "weight_bands" in entry:
        if w is None:
            dose.missing.append("weight_kg")
            return dose
        band = _band(entry["weight_bands"], w)
        if band is None:
            dose.missing.append("weight outside the kb bands")
            return dose
        dose.per_dose = {k: v for k, v in band.items() if k not in ("min_kg", "below_kg")}
        dose.basis = f"weight band {band.get('min_kg', 0)} to {band.get('below_kg', 'up')} kg"
    elif "mg_per_kg_per_dose" in entry:
        if w is None:
            dose.missing.append("weight_kg")
            return dose
        rule = entry["mg_per_kg_per_dose"]
        if isinstance(rule, list):
            band = _band(rule, w)
            if band is None:
                dose.missing.append("weight outside the kb bands")
                return dose
            rule = band["mg_per_kg"]
        dose.per_dose = {"mg": round(float(rule) * w, 1)}
        dose.basis = f"{rule} mg/kg per dose"
    elif not _per_kg_scalar(entry):
        dose.structured = False
        return dose
    elif "mg_per_kg" in entry or "mg_per_kg_single_dose" in entry:
        if w is None:
            dose.missing.append("weight_kg")
            return dose
        rate = float(entry.get("mg_per_kg", entry.get("mg_per_kg_single_dose")))
        dose.per_dose = {"mg": round(rate * w, 1)}
        dose.basis = f"{rate} mg/kg"
    elif "mg_per_kg_per_day" in entry:
        if w is None:
            dose.missing.append("weight_kg")
            return dose
        rate = float(entry["mg_per_kg_per_day"])
        per_day = rate * w
        n = float(entry.get("doses_per_day", 1))
        dose.per_dose = {"mg": round(per_day / n, 1)}
        dose.basis = f"{rate} mg/kg per day"
    elif "steps_mg" in entry:
        start = entry["steps_mg"][0]
        if "frail" in p.flags and "small_frail_start_mg" in entry:
            start = entry["small_frail_start_mg"]
        dose.per_dose = {"mg": start}
        dose.basis = "first titration step"
    elif "phases" in entry:
        dose.per_dose = {"phases": entry["phases"]}
        dose.basis = "phases from the kb"
    elif any(k in entry for k in ("mg", "g", "mg_per_day", "g_per_day", "tablet_mg")):
        keys = ("mg", "g", "mg_per_day", "g_per_day", "tablet_mg")
        dose.per_dose = {k: entry[k] for k in keys if k in entry}
        dose.basis = "fixed dose"
    else:
        dose.structured = False
        return dose
    mg = {k: float(v) for k, v in dose.per_dose.items() if isinstance(v, int | float)}
    mg.update({k: float(v) for k, v in dose.per_dose.get("mg", {}).items()}
              if isinstance(dose.per_dose.get("mg"), Mapping) else {})
    dose.issues += check_dose_range(entry, mg, w, hdt_id)
    return dose


def adjustments(drug_list: Sequence[Drug], issues: Sequence[Issue], p: Patient
                ) -> list[dict[str, Any]]:
    """Dose changes named by active interactions and CPIC entries."""
    out: list[dict[str, Any]] = []
    for issue in issues:
        if not issue.ix_id:
            continue
        e = kb().entry(issue.ix_id).content()
        if "dose_mg" in e:
            out.append({"source": issue.ix_id, "drug": e["a"], "mg": e["dose_mg"],
                        "doses_per_day": e.get("doses_per_day"), "text": e["management"]})
    for entry_id in kb().ids():
        if not entry_id.startswith("pgx.drug."):
            continue
        e = kb().entry(entry_id).content()
        phenotype = p.pgx.get(str(e["gene"]))
        if phenotype is None:
            continue
        rec = e["recommendations"].get(phenotype)
        if rec and any(d.atc and str(e["atc"]) in d.atc for d in drug_list):
            out.append({"source": entry_id, "gene": e["gene"], "phenotype": phenotype,
                        "action": rec["action"], "strength": rec["strength"],
                        "text": rec["text"]})
    return out


def doses_for_regimen(dose_ids: Sequence[str], p: Patient, hdt_id: str | None = None
                      ) -> list[Dose]:
    entries = [kb().entry(i).content() | {"id": i} for i in dose_ids]
    out = [compute_dose(e, p, hdt_id) for e in entries]
    return out


__all__ = ["Dose", "adjustments", "compute_dose", "doses_for_regimen", "drugs_of"]
