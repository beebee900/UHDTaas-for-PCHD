"""Hormone kinetics (inventory item 8): one-compartment elimination per hormone.

Each hormone concentration follows dC/dt = S(t) - k C with k = ln 2 / half-life, where
S is the secretion or infusion rate from the inputs. A starting concentration and
boluses are supported.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Impulse, Inputs, ModelSpec, OdeModel, Params, Port
from atra import contracts as c
from atra.connectors import DTKind

HORMONES = ("melatonin", "cortisol", "t4", "t3", "tsh", "pth")


class HormoneKineticsModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.endocrine.hormone_kinetics",
        twin=DTKind.ENDOCRINE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Decay and accumulation of circulating hormones and hormone doses",
        inputs=tuple(Port(f"{h}_secretion", "1/min", "input:scenario") for h in HORMONES),
        outputs=tuple(Port(h, "1") for h in HORMONES))
    params_stem = "hormone_kinetics"
    state_names = HORMONES
    time_scale_s = 60.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {h: float(inputs.get(f"{h}0", 0.0)) for h in HORMONES}

    def impulses(self, scenario: c.Scenario | None, inputs: Inputs) -> list[Impulse]:
        boluses = list(inputs.get("boluses", []))
        if scenario is not None and scenario.intervention:
            boluses += list(scenario.intervention.get("boluses", []))
        return [(float(b["t_s"]) / self.time_scale_s, {b["hormone"]: float(b["amount"])})
                for b in boluses]

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        return [float(u.get(f"{h}_secretion", 0.0)) - math.log(2) / p[f"half_life_{h}"] * v
                for h, v in zip(HORMONES, y, strict=True)]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        return {h: float(v) for h, v in zip(HORMONES, y, strict=True)}
