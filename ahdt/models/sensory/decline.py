"""Sensory decline (inventory item 4): age curves of hearing threshold and visual acuity.

Each measure stays at its base value until an onset age and then rises as a power of the
years since onset, y = base + rate (age - onset)^power. The four parameters per measure
are fitted to the synthetic cohort by `fit`, and a person's offset is the difference
between their measurement and the curve.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from scipy.optimize import curve_fit

from ahdt.models.arrays import Array
from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from atra import contracts as c
from atra.connectors import DTKind

MEASURES = {"hearing": "hearing_threshold", "vision": "visual_acuity_logmar"}


def curve(age: Array | float, base: float, onset: float, rate: float,
          power: float) -> Array | float:
    years = np.maximum(np.asarray(age, dtype=float) - onset, 0.0)
    return base + rate * years ** power


class SensoryDeclineModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.sensory.sensory_decline",
        twin=DTKind.SENSORY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Expected age-related hearing and vision change",
        inputs=(Port("age", "a"), Port("hearing_offset", "dB"),
                Port("vision_offset", "{logMAR}")),
        outputs=(Port("hearing_threshold", "dB"), Port("visual_acuity_logmar", "{logMAR}")))
    params_stem = "decline"

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        u = {**state, **inputs}
        if u.get("age") is None:
            return {}
        age = float(u["age"])
        out = {}
        for prefix, name in MEASURES.items():
            value = float(curve(age, p[f"{prefix}_base"], p[f"{prefix}_onset"],
                                p[f"{prefix}_rate"], p[f"{prefix}_power"]))
            out[name] = value + float(u.get(f"{prefix}_offset", 0.0))
        return out

    @staticmethod
    def fit(prefix: str, ages: Sequence[float] | Array, values: Sequence[float] | Array,
            start: Sequence[float]) -> dict[str, float]:
        """Least-squares curve parameters for one measure from cohort data."""
        popt, _ = curve_fit(curve, np.asarray(ages), np.asarray(values), p0=list(start),
                            maxfev=20000)
        return {f"{prefix}_{k}": float(v)
                for k, v in zip(("base", "onset", "rate", "power"), popt, strict=True)}
