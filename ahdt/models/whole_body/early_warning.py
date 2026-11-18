"""Early warning (inventory item 14): NEWS2 for adults and PEWS for children.

Both scores are computed from the knowledge-base scoring tables (rule R5). A NEWS2 scale is a
list of bands in ascending order; a band scores when the value is at or below its `upto`.
A PEWS scale is a list of `[min, max]` bands read from the chart grid; a value on a shared
boundary, or in a gap between bands, takes the higher of the nearest bands' scores.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from ahdt.models.reference import default_kb
from atra import contracts as c
from atra.connectors import DTKind

NEWS2_INPUTS = ("respiration_rate", "spo2", "systolic_bp", "pulse", "temperature",
                "consciousness")


def band_score(value: float, bands: Sequence[Mapping[str, Any]]) -> int:
    for band in bands:
        if "upto" not in band or value <= float(band["upto"]):
            return int(band["score"])
    raise ValueError("a scale needs a final band without an upper limit")


def news2(u: Mapping[str, Any], table: Mapping[str, Any]) -> dict[str, int]:
    on_oxygen = bool(u.get("on_oxygen", False))
    if u.get("spo2_scale") == 2:
        spo2_bands = table["spo2_scale2_oxygen" if on_oxygen else "spo2_scale2_air"]
    else:
        spo2_bands = table["spo2_scale1"]
    return {
        "respiration_rate": band_score(float(u["respiration_rate"]), table["respiration_rate"]),
        "spo2": band_score(float(u["spo2"]), spo2_bands),
        "supplemental_oxygen": int(table["supplemental_oxygen"]["oxygen" if on_oxygen
                                                                 else "air"]),
        "systolic_bp": band_score(float(u["systolic_bp"]), table["systolic_bp"]),
        "pulse": band_score(float(u["pulse"]), table["pulse"]),
        "consciousness": int(table["consciousness"][str(u["consciousness"])]),
        "temperature": band_score(float(u["temperature"]), table["temperature"]),
    }


def response_band(total: int, components: Mapping[str, int],
                  bands: Sequence[Mapping[str, Any]]) -> str:
    chosen = None
    for band in bands:
        lo, hi = band.get("min_total"), band.get("max_total")
        if lo is not None and total >= lo and (hi is None or total <= hi):
            chosen = band["band"]
    single = next((b for b in bands if "single_parameter_score" in b), None)
    if single is not None and chosen == bands[0]["band"] and any(
            v >= single["single_parameter_score"] for v in components.values()):
        chosen = single["band"]
    if chosen is None:
        raise ValueError(f"no response band for a total of {total}")
    return str(chosen)


def range_score(value: float, bands: Sequence[Mapping[str, Any]]) -> int:
    def distance(band: Mapping[str, Any]) -> float:
        lo, hi = band.get("min"), band.get("max")
        if lo is not None and value < lo:
            return float(lo) - value
        if hi is not None and value > hi:
            return value - float(hi)
        return 0.0

    nearest = min(distance(b) for b in bands)
    return max(int(b["score"]) for b in bands if distance(b) == nearest)


PEWS_AGE_TABLES = ("pews.scoring.0_11m", "pews.scoring.1_4y", "pews.scoring.5_12y",
                   "pews.scoring.13y")
PEWS_REQUIRED = ("respiration_rate", "pulse", "systolic_bp", "spo2")


def pews(u: Mapping[str, Any], age_table: Mapping[str, Any],
         common: Mapping[str, Any]) -> dict[str, int] | None:
    """PEWS components; None when a required vital sign is missing."""
    if any(u.get(k) is None for k in PEWS_REQUIRED):
        return None
    scores = {
        "respiration_rate": range_score(float(u["respiration_rate"]),
                                        age_table["respiration_rate"]),
        "heart_rate": range_score(float(u["pulse"]), age_table["heart_rate"]),
        "systolic_bp": range_score(float(u["systolic_bp"]), age_table["systolic_bp"]),
        "spo2": range_score(float(u["spo2"]), common["spo2"]),
    }
    if u.get("respiratory_distress") is not None:
        scores["respiratory_distress"] = int(
            common["respiratory_distress"][str(u["respiratory_distress"])])
    if u.get("respiratory_support") in common["respiratory_support_device"]:
        scores["oxygen"] = int(common["respiratory_support_device"][u["respiratory_support"]])
    elif u.get("oxygen_flow") is not None:
        scores["oxygen"] = range_score(float(u["oxygen_flow"]), common["oxygen_flow_l_min"])
    elif u.get("fio2") is not None:
        scores["oxygen"] = range_score(float(u["fio2"]), common["oxygen_fio2_percent"])
    if u.get("capillary_refill") is not None:
        scores["capillary_refill"] = range_score(float(u["capillary_refill"]),
                                                 common["capillary_refill_s"])
    return scores


def pews_level(total: int, triggers: Sequence[str], escalation: Mapping[str, Any]) -> str | None:
    """The highest escalation level set by the total or by a trigger; None below level low."""
    order = [lv["level"] for lv in escalation["levels"]]
    hits = [lv["level"] for lv in escalation["levels"]
            if total >= lv["min_total"] and total <= lv.get("max_total", total)]
    hits += [t["level"] for t in escalation["triggers"] if t["trigger"] in triggers]
    return max(hits, key=order.index) if hits else None


def pews_table(kb: Any, age_years: float) -> Mapping[str, Any]:
    months = age_years * 12
    for entry_id in PEWS_AGE_TABLES:
        table = kb.entry(entry_id).content()
        if table["age_min_months"] <= months < table["age_max_months"] + 1:
            return dict(table)
    raise ValueError(f"no PEWS chart for age {age_years} years")


class EarlyWarningModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.whole_body.early_warning",
        twin=DTKind.WHOLE_BODY, family=c.ModelFamily.SEMANTIC, tier=c.Tier.T2,
        intended_use="Physiological early-warning score and escalation band",
        inputs=(Port("respiration_rate", "/min", "field:9279-1"),
                Port("spo2", "%", "field:59408-5"),
                Port("systolic_bp", "mm[Hg]", "field:8480-6"),
                Port("pulse", "/min", "field:8867-4"),
                Port("temperature", "Cel", "field:8310-5"),
                Port("consciousness", "{ACVPU}"),
                Port("on_oxygen", "1"),
                Port("spo2_scale", "1"),
                Port("age", "a"),
                Port("respiratory_distress", "{grade}"),
                Port("respiratory_support", "{device}"),
                Port("oxygen_flow", "L/min"),
                Port("fio2", "%"),
                Port("capillary_refill", "s"),
                Port("pews_triggers", "{trigger}")),
        outputs=(Port("news2", "{score}"), Port("news2_band", "{band}"),
                 Port("pews", "{score}"), Port("pews_level", "{level}")),
        explainers=("rules.trace",),
        source="Royal College of Physicians. National Early Warning Score (NEWS) 2: "
               "standardising the assessment of acute-illness severity in the NHS. London: "
               "RCP; 2017. NHS England. National PEWS observation and escalation charts. "
               "2023. Scoring tables in kb/news2.yaml and kb/pews.yaml")

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        kb = self.kb or default_kb()
        u = {**state, **inputs}
        out: dict[str, Any] = {}
        table = kb.entry("news2.scoring").content()
        adult = u.get("age") is None or float(u["age"]) >= float(table["min_age_years"])
        if adult and all(u.get(k) is not None for k in NEWS2_INPUTS):
            components = news2(u, table)
            total = sum(components.values())
            out["news2"] = float(total)
            out["news2_band"] = response_band(total, components, kb.resolve("news2.bands")["bands"])
            out.update({f"news2_{k}": float(v) for k, v in components.items()})
        elif not adult:
            scores = pews(u, pews_table(kb, float(u["age"])),
                          kb.entry("pews.scoring.common").content())
            if scores is not None:
                total = sum(scores.values())
                out["pews"] = float(total)
                out["pews_level"] = pews_level(total, list(u.get("pews_triggers") or []),
                                               kb.entry("pews.escalation").content())
                out.update({f"pews_{k}": float(v) for k, v in scores.items()})
        return out
