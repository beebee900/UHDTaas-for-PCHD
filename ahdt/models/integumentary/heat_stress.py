"""Heat stress (inventory item 12).

The heat index is computed by the procedure of the US National Weather Service: the simple
Steadman formula first, and the Rothfusz regression with its low- and high-humidity
adjustments when the simple value reaches 80 degF. The core temperature comes from the
thermoregulation model through the inputs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from atra import contracts as c
from atra.connectors import DTKind


def heat_index_f(t_f: float, rh: float, p: Params) -> float:
    simple = 0.5 * (t_f + 61.0 + (t_f - 68.0) * 1.2 + rh * 0.094)
    if (simple + t_f) / 2 < 80.0:
        return simple
    hi = (p["c1"] + p["c2"] * t_f + p["c3"] * rh + p["c4"] * t_f * rh + p["c5"] * t_f ** 2
          + p["c6"] * rh ** 2 + p["c7"] * t_f ** 2 * rh + p["c8"] * t_f * rh ** 2
          + p["c9"] * t_f ** 2 * rh ** 2)
    if rh < 13 and 80 <= t_f <= 112:
        hi -= (13 - rh) / 4 * math.sqrt((17 - abs(t_f - 95.0)) / 17)
    elif rh > 85 and 80 <= t_f <= 87:
        hi += (rh - 85) / 10 * (87 - t_f) / 5
    return hi


class HeatStressModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.integumentary.heat_stress",
        twin=DTKind.INTEGUMENTARY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Heat index of the person's environment and core temperature",
        inputs=(Port("air_temperature", "Cel", "connector:ExposomeConnector#temp_c"),
                Port("relative_humidity", "%", "connector:ExposomeConnector#humidity"),
                Port("core_temp", "Cel", "model:ahdt.integumentary.thermoregulation#core_temp")),
        outputs=(Port("heat_index", "Cel"), Port("core_temp", "Cel")),
        explainers=("counterfactual.scenario",))
    params_stem = "heat_stress"

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        u = {**state, **inputs}
        out: dict[str, Any] = {}
        if u.get("air_temperature") is not None and u.get("relative_humidity") is not None:
            t_f = float(u["air_temperature"]) * 9 / 5 + 32
            out["heat_index"] = (heat_index_f(t_f, float(u["relative_humidity"]), p) - 32) * 5 / 9
        if u.get("core_temp") is not None:
            out["core_temp"] = float(u["core_temp"])
        return out
