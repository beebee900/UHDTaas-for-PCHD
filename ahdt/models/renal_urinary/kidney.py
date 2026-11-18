"""Kidney and renal function (inventory item 7).

- eGFR by the race-free CKD-EPI 2021 creatinine equation (Inker et al. 2021).
- Serum creatinine by one-compartment kinetics in total body water (Watson 1980): daily
  production balances the baseline GFR at the baseline creatinine, and the GFR is the
  baseline GFR times `gfr_factor` (lowered by an AKI driver or calibrated to the
  person's creatinine).
- AKI stage by the KDIGO criteria, read from the knowledge base. The reference for the
  absolute-rise criterion follows falls in creatinine with a 48 h time constant and holds
  during rises, so a rise is measured against the recent low.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from ahdt.models.reference import default_kb, person_value
from atra import contracts as c
from atra.connectors import DTKind

CREATININE_CODES = {"14682-9": "creatinine", "2160-0": "creatinine", "38483-4": "creatinine"}


def ckd_epi_2021(creatinine_umol: float, age: float, female: bool, p: Params) -> float:
    scr = creatinine_umol / p["creatinine_mw_factor"]
    kappa = p["kappa_f"] if female else p["kappa_m"]
    alpha = p["alpha_f"] if female else p["alpha_m"]
    egfr = float(p["ckd_a"] * min(scr / kappa, 1.0) ** alpha
                 * max(scr / kappa, 1.0) ** p["beta"] * p["age_base"] ** age)
    return egfr * (p["female_factor"] if female else 1.0)


def total_body_water(age: float, height_cm: float, weight_kg: float, female: bool) -> float:
    """Watson et al. (1980), litres."""
    if female:
        return -2.097 + 0.1069 * height_cm + 0.2466 * weight_kg
    return 2.447 - 0.09516 * age + 0.1074 * height_cm + 0.3362 * weight_kg


def body_surface_area(height_cm: float, weight_kg: float) -> float:
    """Mosteller (1987), m2."""
    return math.sqrt(height_cm * weight_kg / 3600.0)


def kdigo_stage(creatinine: float, baseline: float, rise_48h: float,
                criteria: Mapping[str, Any]) -> int:
    ratio = creatinine / baseline if baseline > 0 else 1.0
    bands = criteria["creatinine_ratio_bands"]
    if ratio >= bands[2] or creatinine >= criteria["stage3_creatinine_umol_l"]:
        return 3
    if ratio >= bands[1]:
        return 2
    if ratio >= bands[0] or rise_48h >= criteria["creatinine_rise_umol_l"]:
        return 1
    return 0


class KidneyModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.renal_urinary.kidney_and_renal_function",
        twin=DTKind.RENAL_URINARY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="eGFR, creatinine trajectory and AKI staging",
        instances=("UBERON:0002113",),
        inputs=(Port("age", "a", "input:demographics"),
                Port("female", "1", "input:demographics"),
                Port("height", "cm", "field:8302-2"),
                Port("weight", "kg", "field:29463-7"),
                Port("baseline_creatinine", "umol/L", "input:history"),
                Port("cardiac_output", "L/min",
                     "facet:UBERON:0000948/haemodynamics#cardiac_output"),
                Port("haematocrit", "%", "field:4544-3")),
        outputs=(Port("creatinine", "umol/L", substance="creatinine"),
                 Port("egfr", "mL/min/{1.73_m2}"), Port("creatinine_clearance", "mL/min"),
                 Port("aki_stage", "1"), Port("filtration_fraction", "1"),
                 Port("gfr_factor", "1")),
        validity={"age_years": [18, 100]},
        explainers=("sensitivity.local", "counterfactual.scenario"),
        obs_map=CREATININE_CODES)
    params_stem = "kidney"
    state_names = ("creatinine", "creatinine_reference")
    time_scale_s = 3600.0


    def criteria(self) -> Mapping[str, Any]:
        content: Mapping[str, Any] = (self.kb or default_kb()).entry(
            "severity.aki.kdigo").content()
        return content

    @staticmethod
    def _person(u: Mapping[str, Any]) -> tuple[float, bool, float, float]:
        return (float(person_value(u, "age")), bool(person_value(u, "female")),
                float(person_value(u, "height")), float(person_value(u, "weight")))

    def baseline_gfr(self, p: Params, u: Mapping[str, Any]) -> tuple[float, float]:
        """(absolute baseline GFR in mL/min, baseline creatinine in umol/L)."""
        age, female, height, weight = self._person(u)
        base = float(u.get("baseline_creatinine") or person_value(
            u, "baseline_creatinine_female" if female else "baseline_creatinine_male"))
        egfr = ckd_epi_2021(base, age, female, p)
        return egfr * body_surface_area(height, weight) / 1.73, base

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        _, base = self.baseline_gfr(p, inputs)
        return {"creatinine": base, "creatinine_reference": base}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        age, female, height, weight = self._person(u)
        gfr_b, base = self.baseline_gfr(p, u)
        volume_ml = total_body_water(age, height, weight, female) * 1000.0
        production = gfr_b * base * 60.0
        clearance = gfr_b * float(u.get("gfr_factor", p["gfr_factor"])) * y[0] * 60.0
        d_cr = (production - clearance) / volume_ml
        d_min = (y[0] - y[1]) / 48.0 if y[0] < y[1] else 0.0
        return [d_cr, d_min]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        age, female, _, _ = self._person(u)
        gfr_b, base = self.baseline_gfr(p, u)
        factor = float(u.get("gfr_factor", p["gfr_factor"]))
        egfr = ckd_epi_2021(float(y[0]), age, female, p)
        out = {"creatinine": float(y[0]), "egfr": egfr,
               "creatinine_clearance": gfr_b * factor, "gfr_factor": factor,
               "aki_stage": float(kdigo_stage(float(y[0]), base, float(y[0] - y[1]),
                                              self.criteria()))}
        co = u.get("cardiac_output")
        if co is not None:
            hct = float(person_value(u, "haematocrit")) / 100.0
            plasma_flow = float(co) * 1000.0 * p["renal_share"] * (1 - hct)
            out["filtration_fraction"] = gfr_b * factor / plasma_flow
        return out
