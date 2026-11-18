"""Neuron and circuit (inventory item 3), educational fidelity.

The Hodgkin-Huxley (1952) squid axon in its original sign convention, where V is the
displacement from rest and depolarisation is negative; the outputs report the
depolarisation as positive. The circuit is a ring of FitzHugh (1961) units with diffusive
coupling. Model time is in milliseconds; one FitzHugh time unit is taken as 1 ms.
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

RING = 5
SPIKE_MV = 50.0


def _rates(v: float) -> tuple[float, float, float, float, float, float]:
    def ratio(x: float, scale: float) -> float:
        return scale if abs(x) < 1e-9 else x / (math.exp(x / 10) - 1)

    a_m = 0.1 * ratio(v + 25, 10.0)
    b_m = 4 * math.exp(v / 18)
    a_h = 0.07 * math.exp(v / 20)
    b_h = 1 / (math.exp((v + 30) / 10) + 1)
    a_n = 0.01 * ratio(v + 10, 10.0)
    b_n = 0.125 * math.exp(v / 80)
    return a_m, b_m, a_h, b_h, a_n, b_n


class NeuronModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.nervous.neuron_and_circuit",
        twin=DTKind.NERVOUS, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Teaching illustration of action potentials and network excitability",
        inputs=(Port("stimulus", "uA/cm2", "input:scenario"),
                Port("ring_stimulus", "1", "input:scenario")),
        outputs=(Port("membrane_depolarisation", "mV"), Port("fhn_mean_activity", "1")),
        fidelity_note="Educational fidelity: squid axon and a dimensionless ring network",
        explainers=())
    params_stem = "neuron"
    state_names = ("V", "m", "h", "n", *(f"x{i}" for i in range(RING)),
                   *(f"y{i}" for i in range(RING)))
    time_scale_s = 1e-3
    max_step = 0.05

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        state = {"V": 0.0, "m": 0.052932, "h": 0.59612, "n": 0.31768}
        state.update({f"x{i}": -1.0 for i in range(RING)})
        state.update({f"y{i}": 0.5 for i in range(RING)})
        return state

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        v, m, h, n = y[:4]
        a_m, b_m, a_h, b_h, a_n, b_n = _rates(v)
        current = -float(u.get("stimulus", 0.0))
        i_ion = (p["g_Na"] * m ** 3 * h * (v - p["V_Na"]) + p["g_K"] * n ** 4 * (v - p["V_K"])
                 + p["g_L"] * (v - p["V_L"]))
        out = [(current - i_ion) / p["Cm"], a_m * (1 - m) - b_m * m, a_h * (1 - h) - b_h * h,
               a_n * (1 - n) - b_n * n]
        x, w = y[4:4 + RING], y[4 + RING:]
        drive = float(u.get("ring_stimulus", 0.0))
        dx, dw = [], []
        for i in range(RING):
            z = (drive if i == 0 else 0.0) - 0.4
            coupling = p["fhn_coupling"] * (x[i - 1] - x[i])
            dx.append(p["fhn_c"] * (x[i] - x[i] ** 3 / 3 + w[i] + z) + coupling)
            dw.append(-(x[i] - p["fhn_a"] + p["fhn_b"] * w[i]) / p["fhn_c"])
        return out + dx + dw

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        return {"membrane_depolarisation": -float(y[0]),
                "fhn_mean_activity": float(np.mean(y[4:4 + RING]))}

    def events(self, t: Array, series: Mapping[str, Array],
               p: Params) -> list[c.TrajectoryEvent]:
        v = series.get("membrane_depolarisation")
        if v is None:
            return []
        above = v > SPIKE_MV
        onsets = np.flatnonzero(above[1:] & ~above[:-1]) + 1
        return [c.TrajectoryEvent(t=float(t[i]), kind="action_potential") for i in onsets]
