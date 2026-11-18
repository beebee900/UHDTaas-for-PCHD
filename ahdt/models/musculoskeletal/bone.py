"""Bone remodelling and density (inventory item 11): Komarova et al. (2003).

Osteoclasts x1 and osteoblasts x2 interact through autocrine and paracrine power-law
terms; bone mass z (percent of initial) is resorbed by osteoclasts and formed by
osteoblasts above their steady-state numbers. A remodelling cycle starts from a
perturbation of the cell numbers. The bone density trend scales the person's baseline
bone mineral density by z.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from atra import contracts as c
from atra.connectors import DTKind


def steady_cells(p: Params) -> tuple[float, float]:
    gamma = p["g12"] * p["g21"] - (1 - p["g11"]) * (1 - p["g22"])
    x1 = ((p["beta1"] / p["alpha1"]) ** ((1 - p["g22"]) / gamma)
          * (p["beta2"] / p["alpha2"]) ** (p["g21"] / gamma))
    x2 = ((p["beta1"] / p["alpha1"]) ** (p["g12"] / gamma)
          * (p["beta2"] / p["alpha2"]) ** ((1 - p["g11"]) / gamma))
    return x1, x2


class BoneRemodellingModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.musculoskeletal.bone_remodelling_and_density",
        twin=DTKind.MUSCULOSKELETAL, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Bone mass change over remodelling cycles and its density trend",
        instances=("UBERON:0001434",),
        inputs=(Port("bmd0", "g/cm2", "field:38265-5"),),
        outputs=(Port("osteoclasts", "1"), Port("osteoblasts", "1"), Port("bone_mass", "%"),
                 Port("bone_density", "g/cm2")),
        explainers=("sensitivity.local",))
    params_stem = "bone"
    state_names = ("x1", "x2", "z")
    time_scale_s = 86400.0
    method = "Radau"

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {"x1": p["x1_0"], "x2": p["x2_0"], "z": 100.0}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        x1, x2 = max(y[0], 1e-12), max(y[1], 1e-12)
        x1_bar, x2_bar = steady_cells(p)
        return [p["alpha1"] * x1 ** p["g11"] * x2 ** p["g21"] - p["beta1"] * x1,
                p["alpha2"] * x1 ** p["g12"] * x2 ** p["g22"] - p["beta2"] * x2,
                p["k2"] * max(x2 - x2_bar, 0.0) - p["k1"] * max(x1 - x1_bar, 0.0)]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        out = {"osteoclasts": float(y[0]), "osteoblasts": float(y[1]), "bone_mass": float(y[2])}
        if u.get("bmd0") is not None:
            out["bone_density"] = float(u["bmd0"]) * float(y[2]) / 100.0
        return out
