"""Fluid, electrolyte and acid-base balance (inventory item 7).

- Plasma-water sodium from exchangeable sodium, exchangeable potassium and total body
  water by the Edelman (1958) relation.
- Plasma potassium from the extracellular potassium pool and the extracellular volume.
- pH from bicarbonate and the arterial CO2 tension by the Henderson-Hasselbalch equation;
  bicarbonate returns towards its baseline unless an acid or base load is applied.

Water, sodium and potassium move with the intake and loss rates in the inputs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from ahdt.models.reference import person_value
from ahdt.models.renal_urinary.kidney import total_body_water
from atra import contracts as c
from atra.connectors import DTKind


def henderson_hasselbalch(hco3: float, paco2: float, p: Params) -> float:
    return p["pk_bicarbonate"] + math.log10(hco3 / (p["co2_solubility"] * paco2))


class AcidBaseModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.renal_urinary.fluid_electrolyte_and_acid_base_balance",
        twin=DTKind.RENAL_URINARY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Sodium, potassium, water and acid-base state under intake and losses",
        inputs=(Port("paco2", "mm[Hg]", "facet:UBERON:0002048/gas_exchange#paco2"),
                Port("water_in", "mL/h"), Port("water_out", "mL/h"),
                Port("na_in", "mmol/h"), Port("na_out", "mmol/h"),
                Port("k_in", "mmol/h"), Port("k_out", "mmol/h"),
                Port("acid_load", "mmol/L/h"), Port("age", "a"), Port("female", "1"),
                Port("height", "cm"), Port("weight", "kg"), Port("sodium0", "mmol/L"),
                Port("potassium0", "mmol/L"), Port("hco3_0", "mmol/L")),
        outputs=(Port("sodium", "mmol/L"), Port("potassium", "mmol/L"), Port("hco3", "mmol/L"),
                 Port("ph", "[pH]"), Port("total_body_water", "L")),
        explainers=("sensitivity.local",),
        obs_map={"2951-2": "sodium", "2823-3": "potassium", "1963-8": "hco3"})
    params_stem = "acid_base"
    state_names = ("Na_e", "K_e", "K_ecf", "TBW", "HCO3")
    time_scale_s = 3600.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        tbw = total_body_water(float(person_value(inputs, "age")),
                               float(person_value(inputs, "height")),
                               float(person_value(inputs, "weight")),
                               bool(person_value(inputs, "female")))
        na0 = float(person_value(inputs, "sodium0"))
        k0 = float(person_value(inputs, "potassium0"))
        # Exchangeable cation content implied by the Edelman relation at the initial sodium;
        # split between sodium and potassium in equal parts, which the relation does not fix.
        cations = (na0 - p["edelman_intercept"]) * tbw / p["edelman_slope"]
        return {"Na_e": cations / 2, "K_e": cations / 2, "K_ecf": k0 * tbw * p["ecf_fraction"],
                "TBW": tbw, "HCO3": float(person_value(inputs, "hco3_0"))}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        hco3 = y[4]
        dk = float(u.get("k_in", 0.0)) - float(u.get("k_out", 0.0))
        hco3_0 = float(person_value(u, "hco3_0"))
        return [float(u.get("na_in", 0.0)) - float(u.get("na_out", 0.0)),
                dk,
                dk,
                (float(u.get("water_in", 0.0)) - float(u.get("water_out", 0.0))) / 1000.0,
                (hco3_0 - hco3) / p["hco3_tau"] - float(u.get("acid_load", 0.0))]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        na_e, k_e, k_ecf, tbw, hco3 = y
        paco2 = float(person_value(u, "paco2"))
        return {"sodium": p["edelman_slope"] * (na_e + k_e) / tbw + p["edelman_intercept"],
                "potassium": k_ecf / (tbw * p["ecf_fraction"]), "hco3": float(hco3),
                "ph": henderson_hasselbalch(float(hco3), paco2, p), "total_body_water": float(tbw)}
