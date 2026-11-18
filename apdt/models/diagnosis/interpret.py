"""Result interpretation support (design 05, 5.5.1): reference ranges, critical values,
delta checks and findings derived from measurements. All cut-offs come from the kb.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from ahdt.ingest.fields import field_index
from apdt.integration.critical import CriticalRules, Hit
from apdt.models.context import Patient, kb

Flag = Literal["low", "normal", "high"]
Level = Literal["normal", "warn", "critical"]


@dataclass(frozen=True)
class Interpretation:
    field: str
    value: float
    unit: str
    flag: Flag
    level: Level
    reference: tuple[float | None, float | None]
    critical_hits: tuple[Hit, ...] = ()


@dataclass(frozen=True)
class DeltaResult:
    field: str
    flagged: bool
    reason: str | None
    rule: str | None = None


def _range_entry(field: str) -> Mapping[str, Any] | None:
    entry_id = f"range.{field}"
    return kb().entry(entry_id).content() if entry_id in kb() else None


def _in_band(by: Mapping[str, Any], p: Patient) -> bool:
    if "sex" in by and by["sex"] != p.sex:
        return False
    if "pregnancy" in by and by["pregnancy"] != p.pregnancy:
        return False
    if "patient_group" in by and by["patient_group"] != p.patient_group:
        return False
    months = p.age_years * 12
    if "age_from_months" in by and months < by["age_from_months"]:
        return False
    return not ("age_below_months" in by and months >= by["age_below_months"])


def reference_for(field: str, p: Patient) -> dict[str, Any] | None:
    """The reference, warning and critical limits for a field and patient; the `by`
    overrides that match the patient replace the general limits."""
    entry = _range_entry(field)
    if entry is None:
        return None
    limits = {k: entry.get(k) for k in ("ref_low", "ref_high", "warn_low", "warn_high",
                                         "crit_low", "crit_high")}
    for by in entry.get("by") or []:
        if _in_band(by, p):
            limits.update({k: v for k, v in by.items()
                           if k in limits and v is not None})
    return {**limits, "unit": entry.get("unit")}


def _lt(value: float, limit: float | None) -> bool:
    return limit is not None and value < float(limit)


def _gt(value: float, limit: float | None) -> bool:
    return limit is not None and value > float(limit)


def interpret(field: str, value: float, p: Patient) -> Interpretation | None:
    """Flag a result against its reference range and list the critical rules it meets."""
    ref = reference_for(field, p)
    if ref is None:
        return None
    flag: Flag = ("low" if _lt(value, ref["ref_low"])
                  else "high" if _gt(value, ref["ref_high"]) else "normal")
    level: Level = "normal"
    if _lt(value, ref["warn_low"]) or _gt(value, ref["warn_high"]):
        level = "warn"
    if _lt(value, ref["crit_low"]) or _gt(value, ref["crit_high"]):
        level = "critical"
    hits: tuple[Hit, ...] = ()
    fref = field_index().by_name(field)
    if fref is not None:
        rules = CriticalRules(kb())
        hits = tuple(rules.check(fref.code, value, fref.field.ucum, age_years=p.age_years))
        if hits:
            level = "critical"
    return Interpretation(field, value, str(ref["unit"]), flag, level,
                          (ref["ref_low"], ref["ref_high"]), hits)


def delta_check(field: str, current: float, previous: float, elapsed_h: float
                ) -> DeltaResult:
    """Compare a result with the previous one. Rate-of-change limits come from
    `plausibility.rules`; a creatinine rise is read against the KDIGO criteria."""
    if elapsed_h <= 0:
        raise ValueError("elapsed_h must be positive")
    for rule in kb().entry("plausibility.rules").content()["rules"]:
        if rule.get("field") != field:
            continue
        if "max_change_per_hour" in rule:
            rate = abs(current - previous) / elapsed_h
            if rate > float(rule["max_change_per_hour"]):
                return DeltaResult(field, True, "change faster than a physiological rate",
                                   rule["id"])
        if "max_change_per_day" in rule:
            rate = abs(current - previous) / (elapsed_h / 24.0)
            if rate > float(rule["max_change_per_day"]):
                return DeltaResult(field, True, "change faster than a physiological rate",
                                   rule["id"])
    if field == "creatinine":
        aki = kb().entry("severity.aki.kdigo").content()
        rise = current - previous
        if elapsed_h <= float(aki["creatinine_rise_window_h"]) and \
                rise >= float(aki["creatinine_rise_umol_l"]):
            return DeltaResult(field, True, "rise meets the KDIGO creatinine criterion",
                               "severity.aki.kdigo")
        if previous > 0 and current / previous >= float(aki["creatinine_ratio_bands"][0]) \
                and elapsed_h <= float(aki["creatinine_ratio_window_days"]) * 24.0:
            return DeltaResult(field, True, "ratio meets the KDIGO creatinine criterion",
                               "severity.aki.kdigo")
    return DeltaResult(field, False, None)


def _threshold_met(derive: Mapping[str, Any], th: Mapping[str, Any], value: float,
                   measurements: Mapping[str, float], p: Patient) -> bool | None:
    """Whether the threshold is met; None when this kb entry shape is not evaluable."""
    field = derive["field"]
    if "at_or_above" in th:
        return value >= float(th["at_or_above"])
    if "above" in th:
        return value > float(th["above"])
    if "at_or_below" in th:
        return value <= float(th["at_or_below"])
    if "below" in th:
        return value < float(th["below"])
    if "by_age" in th:
        months = p.age_years * 12
        for band in th["by_age"]:
            if band.get("age_from_months", 0) <= months < band["age_below_months"]:
                return value >= float(band["at_or_above"])
        return False
    if "systolic_bp_below" in th and field == "sbp":
        return value < float(th["systolic_bp_below"])
    if "pulse_above" in th and field == "heart_rate":
        return value > float(th["pulse_above"])
    if "systolic_at_or_above" in th:
        dbp = measurements.get("dbp")
        return (measurements.get("sbp", float("-inf")) >= float(th["systolic_at_or_above"])
                or (dbp is not None and dbp >= float(th["diastolic_at_or_above"])))
    return None


def _anaemia(value_g_dl: float, p: Patient) -> bool | None:
    months = p.age_years * 12
    for g in kb().entry("severity.anaemia.who").content()["groups"]:
        if "pregnancy" in g:
            if p.pregnancy != g["pregnancy"]:
                continue
        elif ((p.pregnancy != "none" and g.get("sex") == "female")
              or ("sex" in g and g["sex"] != p.sex)):
            continue
        if "age_from_months" in g and not g["age_from_months"] <= months < g["age_below_months"]:
            continue
        return bool(value_g_dl * 10.0 < float(g["anaemia_below"]))
    return None


def derive_findings(measurements: Mapping[str, float], p: Patient) -> dict[str, bool]:
    """Measurement findings (kb `derive`) that the measurements make present or absent."""
    out: dict[str, bool] = {}
    for entry_id in kb().ids():
        if not entry_id.startswith("find."):
            continue
        derive = kb().entry(entry_id).content().get("derive")
        if not derive or derive["field"] not in measurements:
            continue
        value = float(measurements[derive["field"]])
        th_id = derive["threshold"]
        if th_id == "severity.anaemia.who":
            met = _anaemia(value, p)
        elif th_id.startswith("range."):
            ref = reference_for(derive["field"], p)
            met = None if ref is None else _gt(value, ref["ref_high"])
        else:
            met = _threshold_met(derive, kb().entry(th_id).content(), value, measurements, p)
        if met is not None:
            out[entry_id] = met
    return out
