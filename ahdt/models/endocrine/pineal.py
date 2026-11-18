"""Pineal melatonin (inventory item 8): Brown et al. (1997).

Synthesis A(t) rises after the onset time towards A_max and decays after the offset;
pineal melatonin H1 is released into plasma H2, which is cleared first-order. Onset and
offset follow the circadian phase supplied by the sleep model (as `clock_min`) and are
calibrated to the person's melatonin measurements.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from atra import contracts as c
from atra.connectors import DTKind

DAY_MIN = 1440.0


def synthesis(clock_min: float, p: Params) -> float:
    lam = math.log(2) / p["tau_lamda"]
    alpha = math.log(2) / p["tau_alpha"]
    t = clock_min % DAY_MIN
    if t < p["t_on"] and t + DAY_MIN < p["t_off"]:
        t += DAY_MIN
    if p["t_on"] <= t < p["t_off"]:
        return p["A_max"] * (1 - math.exp(-lam * (t - p["t_on"]))) / (
            1 - math.exp(-lam * (p["t_off"] - p["t_on"])))
    since_off = (t - p["t_off"]) % DAY_MIN
    return p["A_max"] * math.exp(-alpha * since_off)


class PinealModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.endocrine.pineal",
        twin=DTKind.ENDOCRINE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Plasma melatonin rhythm and dim-light melatonin onset",
        instances=("UBERON:0001905",),
        inputs=(Port("clock_min", "min", "input:clock"),),
        outputs=(Port("melatonin", "pmol/L"), Port("pineal_melatonin", "pmol/L"),
                 Port("synthesis_rate", "pmol/L/min"), Port("circadian_phase", "h")),
        obs_map={"melatonin": "melatonin"})
    params_stem = "pineal"
    state_names = ("H1", "H2")
    time_scale_s = 60.0
    max_step = 5.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {"H1": 0.0, "H2": 0.0}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        beta_i = math.log(2) / p["tau_I"]
        beta_c = math.log(2) / p["tau_C"]
        a = synthesis(t + float(u.get("clock_min", 0.0)), p)
        return [-beta_i * y[0] + a, beta_i * y[0] - beta_c * y[1]]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        clock = t + float(u.get("clock_min", 0.0))
        return {"melatonin": float(y[1]), "pineal_melatonin": float(y[0]),
                "synthesis_rate": synthesis(clock, p),
                "circadian_phase": ((clock - p["t_on"]) / 60.0) % 24.0}
