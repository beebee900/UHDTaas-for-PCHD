"""Platelets (inventory item 10).

Platelets are released from a two-stage megakaryocyte chain. Production rises with the
relative platelet deficit (a reduced thrombopoietin feedback) and platelets are lost by
senescence and by consumption (for example in malaria, sepsis or bleeding).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from ahdt.models.reference import person_value
from atra import contracts as c
from atra.connectors import DTKind


class PlateletModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.haematological.platelets",
        twin=DTKind.HAEMATOLOGICAL, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Platelet count under consumption and marrow suppression",
        instances=("UBERON:0000178",),
        inputs=(Port("platelets0", "10*3/uL", "field:777-3"),
                Port("consumption_rate", "/d", "input:condition"),
                Port("marrow_suppression", "1", "input:condition")),
        outputs=(Port("platelets", "10*3/uL"), Port("platelet_production", "10*3/uL/d")),
        explainers=("counterfactual.scenario",),
        obs_map={"777-3": "platelets", "26515-7": "platelets"})
    params_stem = "platelets"
    state_names = ("PLT", "M1", "M2")
    time_scale_s = 86400.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        plt0 = float(person_value(inputs, "platelets0"))
        stage = plt0 / p["lifespan"] * p["maturation_days"] / 2
        return {"PLT": plt0, "M1": stage, "M2": stage}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        plt, m1, m2 = y
        plt0 = float(person_value(u, "platelets0"))
        deficit = max(0.0, 1 - plt / plt0)
        production = (plt0 / p["lifespan"] * (1 + p["feedback_gain"] * deficit)
                      * (1 - float(u.get("marrow_suppression", 0.0))))
        k = 2.0 / p["maturation_days"]
        return [k * m2 - plt / p["lifespan"] - float(u.get("consumption_rate", 0.0)) * plt,
                production - k * m1, k * m1 - k * m2]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        return {"platelets": float(y[0]),
                "platelet_production": 2.0 / p["maturation_days"] * float(y[2])}
