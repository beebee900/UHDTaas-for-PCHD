"""Baroreflex regulation (inventory item 1, cardiovascular control).

Ursino (1998): the carotid sinus pressure is filtered by a first-order block with a real
zero, mapped to the afferent firing rate by a sigmoid, and drives sympathetic and vagal
efferent activity. The effectors (heart period, left ventricular elastance and splanchnic
resistance) follow the efferent activity after a pure delay through first-order dynamics.

The outputs are the heart rate and the contractility and resistance factors that the
heart model reads. Both factors are 1 at the resting set point P_n.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from ahdt.models.dde import integrate_dde
from atra import contracts as c
from atra.connectors import DTKind

STEP_S = 0.05


def afferent(p_tilde: float, p: Params) -> float:
    x = math.exp((p_tilde - p["P_n"]) / p["k_ab"])
    return (p["f_ab_min"] + p["f_ab_max"] * x) / (1 + x)


def sympathetic(f_ab: float, p: Params) -> float:
    return p["f_es_inf"] + (p["f_es_0"] - p["f_es_inf"]) * math.exp(-p["k_es"] * f_ab)


def vagal(f_ab: float, p: Params) -> float:
    x = math.exp((f_ab - p["f_ab_0"]) / p["k_ev"])
    return (p["f_ev_0"] + p["f_ev_inf"] * x) / (1 + x)


def log_drive(f_es: float, p: Params, gain: float) -> float:
    return gain * math.log(f_es - p["f_es_min"] + 1) if f_es >= p["f_es_min"] else 0.0


class BaroreflexModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.cardiovascular.baroreflex_regulation",
        twin=DTKind.CARDIOVASCULAR, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Short-term autonomic control of heart rate, contractility and resistance",
        inputs=(Port("map", "mm[Hg]", "model:ahdt.cardiovascular.heart_chambers_and_valves#map"),),
        outputs=(Port("heart_rate", "/min"), Port("contractility_factor", "1"),
                 Port("resistance_factor", "1"), Port("sympathetic_activity", "Hz"),
                 Port("vagal_activity", "Hz"), Port("afferent_activity", "Hz")),
        validity={"timescale": "seconds to minutes"},
        explainers=("sensitivity.local",))
    params_stem = "baroreflex"
    state_names = ("P_tilde", "dE", "dR", "dTs", "dTv")

    def _steady(self, p: Params, pressure: float) -> Array:
        f_ab = afferent(pressure, p)
        f_es, f_ev = sympathetic(f_ab, p), vagal(f_ab, p)
        return np.array([pressure, log_drive(f_es, p, p["G_E"]), log_drive(f_es, p, p["G_R"]),
                         log_drive(f_es, p, p["G_Ts"]), p["G_Tv"] * f_ev])

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        pressure = float(inputs.get("map", p["P_n"]))
        return dict(zip(self.state_names, (float(v) for v in self._steady(p, pressure)),
                        strict=True))

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        raise NotImplementedError("the baroreflex has delays; use integrate()")

    def _delay_rhs(self, p: Params, u: Any) -> Any:
        def pressure(t: float) -> float:
            return float(u(t).get("map", p["P_n"]))

        def f(t: float, y: Array, lag: Any) -> list[float]:
            dp = (pressure(t + 1e-3) - pressure(t - 1e-3)) / 2e-3
            out = [(pressure(t) + p["tau_z"] * dp - y[0]) / p["tau_p"]]

            def efferent(delay: float) -> tuple[float, float]:
                f_ab = afferent(float(lag(t - delay)[0]), p)
                return sympathetic(f_ab, p), vagal(f_ab, p)

            out.append((log_drive(efferent(p["D_E"])[0], p, p["G_E"]) - y[1]) / p["tau_E"])
            out.append((log_drive(efferent(p["D_R"])[0], p, p["G_R"]) - y[2]) / p["tau_R"])
            out.append((log_drive(efferent(p["D_Ts"])[0], p, p["G_Ts"]) - y[3]) / p["tau_Ts"])
            out.append((p["G_Tv"] * efferent(p["D_Tv"])[1] - y[4]) / p["tau_Tv"])
            return out

        return f

    def integrate(self, p: Params, y0: Array, t_eval: Array, u: Any, *,
                  param_path: Any = None, impulses: Any = ()) -> Array:
        return integrate_dde(self._delay_rhs(p, u), np.asarray(y0, dtype=float), t_eval, STEP_S)

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        f_ab = afferent(float(y[0]), p)
        period = p["T_0"] + y[3] + y[4]
        rest = self._steady(p, p["P_n"])
        return {"heart_rate": 60.0 / period,
                "contractility_factor": (p["E_0"] + y[1]) / (p["E_0"] + rest[1]),
                "resistance_factor": (p["R_0"] + y[2]) / (p["R_0"] + rest[2]),
                "sympathetic_activity": sympathetic(f_ab, p), "vagal_activity": vagal(f_ab, p),
                "afferent_activity": f_ab}
