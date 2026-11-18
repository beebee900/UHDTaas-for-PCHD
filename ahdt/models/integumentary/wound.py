"""Wound healing (inventory item 12).

The healed fraction h follows logistic closure, dh/dt = k_eff h (1 - h), where the
effective rate is the person's rate k reduced by hyperglycaemia and by poor perfusion.
The wound area is the initial area times (1 - h). The rate is calibrated to the measured
wound areas.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from atra import contracts as c
from atra.connectors import DTKind


def effective_rate(p: Params, u: Mapping[str, Any]) -> float:
    rate = p["k"] * min(float(u.get("perfusion_index", 1.0)), 1.0)
    excess = max(float(u.get("hba1c", p["hba1c_ref"])) - p["hba1c_ref"], 0.0)
    return rate / (1 + p["hba1c_slope"] * excess)


class WoundHealingModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.integumentary.wound_healing",
        twin=DTKind.INTEGUMENTARY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Expected wound closure and the effect of glycaemia and perfusion",
        inputs=(Port("area0", "cm2", "input:wound_measurement"), Port("hba1c", "%", "field:4548-4"),
                Port("perfusion_index", "1", "input:perfusion")),
        outputs=(Port("healed_fraction", "1"), Port("wound_area", "cm2")),
        explainers=("counterfactual.scenario",),
        obs_map={"wound_area": "wound_area"})
    params_stem = "wound"
    state_names = ("h",)
    time_scale_s = 86400.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {"h": p["healed0"]}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        return [effective_rate(p, u) * y[0] * (1 - y[0])]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        out = {"healed_fraction": float(y[0])}
        if u.get("area0") is not None:
            out["wound_area"] = float(u["area0"]) * (1 - float(y[0]))
        return out
