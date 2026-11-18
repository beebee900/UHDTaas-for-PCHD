"""HPA axis (inventory item 8): Gupta et al. (2007) scaled model with the pituitary
glucocorticoid receptor, which has a normal and a low-cortisol steady state.

Scaled time is K_od * T, with K_od the cortisol degradation rate (ln 2 over the half-life).
The scaled CRH drive is 1 + f, where f is the stress drive from the Nervous twin; here the
constant drive is modulated by the circadian phase, which Gupta et al. leave out.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from atra import contracts as c
from atra.connectors import DTKind


class HpaModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.endocrine.hpa_axis",
        twin=DTKind.ENDOCRINE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Cortisol rhythm and its response to stress",
        instances=("UBERON:0001898", "UBERON:0000007", "UBERON:0002369"),
        inputs=(Port("stress_drive", "1", "connector:NeuroEndocrineConnector#stress_drive"),
                Port("clock_h", "h", "connector:NeuroEndocrineConnector#circadian_phase")),
        outputs=(Port("cortisol", "nmol/L"), Port("crh_drive", "1"), Port("acth", "1"),
                 Port("gr", "1"), Port("cortisol_scaled", "1"), Port("stress_drive", "1")),
        explainers=("sensitivity.local",),
        obs_map={"2143-6": "cortisol"})
    params_stem = "hpa"
    state_names = ("c", "a", "r", "o")
    time_scale_s = 60.0

    def k_od(self, p: Params) -> float:
        return math.log(2) / p["cortisol_half_life"]

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        """The low-receptor (normal) steady state without stress or rhythm."""
        y = np.array([0.6, 0.055, 0.01, 0.055])
        for _ in range(20000):
            y = y + 0.01 * np.asarray(self._scaled(y, p, 0.0, 1.0))
        return dict(zip(self.state_names, (float(v) for v in y), strict=True))

    def _scaled(self, y: Array, p: Params, f: float, drive: float) -> list[float]:
        cc, a, r, o = y
        return [drive * (1 + f) / (1 + o / p["ki1"]) - p["kcd"] * cc,
                cc / (1 + o * r / p["ki2"]) - p["kad"] * a,
                (o * r) ** 2 / (p["k"] + (o * r) ** 2) + p["kcr"] - p["krd"] * r,
                a - o]

    def _drive(self, t_min: float, p: Params, u: Mapping[str, Any]) -> float:
        clock = t_min / 60.0 + float(u.get("clock_h", 0.0))
        return 1 + p["circadian_amplitude"] * math.cos(2 * math.pi * (clock - p["peak_phase_h"])
                                                       / 24.0)

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        rate = self.k_od(p)
        f = float(u.get("stress_drive", 0.0))
        return [rate * d for d in self._scaled(y, p, f, self._drive(t, p, u))]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        return {"cortisol": float(y[3]) * p["cortisol_scale"], "crh_drive": float(y[0]),
                "acth": float(y[1]), "gr": float(y[2]), "cortisol_scaled": float(y[3]),
                "stress_drive": float(u.get("stress_drive", 0.0))}
