"""Glucose-insulin regulation (inventory item 8, pancreatic islets and metabolic regulation).

`GlucoseInsulinModel` is the Dalla Man, Rizza and Cobelli (2007) meal model: glucose and
insulin kinetics, endogenous glucose production, utilisation, renal excretion, insulin
secretion and the gut absorption subsystem. A coupled appearance rate `Ra` from the
Digestive twin replaces the internal gut subsystem when it is supplied.

`MinimalModel` is the Bergman combined minimal model. It reads a frequently sampled
intravenous glucose tolerance test (FSIGT) and returns insulin sensitivity and glucose
effectiveness.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import least_squares

from ahdt.models.arrays import Array
from ahdt.models.base import Impulse, Inputs, ModelSpec, OdeModel, Params, Port
from ahdt.models.digestive.gut import GUT_STATES, gut_rates, last_dose, meals
from atra import contracts as c
from atra.connectors import DTKind
from atra.units import convert

MGDL_TO_MMOLL = convert(1.0, "mg/dL", "mmol/L", substance="glucose")
GLUCOSE_CODES = ("15074-8", "2339-0", "2345-7", "41653-7")


class GlucoseInsulinModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.endocrine.glucose_insulin_and_metabolic_regulation",
        twin=DTKind.ENDOCRINE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Plasma glucose and insulin response to meals for glycaemic forecasts",
        instances=("UBERON:0001264",),
        inputs=(Port("Ra", "mg/kg/min", "facet:UBERON:0000160/absorption#absorption_rate"),
                Port("meals", "g", "input:scenario")),
        outputs=(Port("glucose", "mmol/L", substance="glucose"),
                 Port("glucose_mgdl", "mg/dL"), Port("insulin", "pmol/L"),
                 Port("insulin_secretion", "pmol/kg/min"), Port("EGP", "mg/kg/min"),
                 Port("utilisation", "mg/kg/min"), Port("Ra", "mg/kg/min"),
                 Port("renal_excretion", "mg/kg/min")),
        validity={"population": "adults without diabetes", "age_years": [18, 90]},
        explainers=("sensitivity.local", "counterfactual.scenario"),
        obs_map=dict.fromkeys(GLUCOSE_CODES, "glucose"))
    params_stem = "glucose_insulin"
    state_names = ("G_p", "G_t", "I_l", "I_p", "X", "I_1", "I_d", "I_po", "Y", *GUT_STATES)
    time_scale_s = 60.0
    max_step = 5.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        """Basal state: plasma compartments at the basal concentrations, the tissue glucose
        and liver insulin that balance their plasma equations, and an empty gut."""
        g_pb = p["G_b"] * p["V_G"]
        i_pb = p["I_b"] * p["V_I"]
        i_pob = p["S_b"] / p["gamma"]
        egp_b = p["k_p1"] - p["k_p2"] * g_pb - p["k_p3"] * p["I_b"] - p["k_p4"] * i_pob
        g_tb = (p["F_cns"] - egp_b + p["k_1"] * g_pb) / p["k_2"]
        i_lb = (p["m_2"] + p["m_4"]) * i_pb / p["m_1"]
        return {"G_p": g_pb, "G_t": g_tb, "I_l": i_lb, "I_p": i_pb, "X": 0.0, "I_1": p["I_b"],
                "I_d": p["I_b"], "I_po": i_pob, "Y": 0.0, "Q_sto1": 0.0, "Q_sto2": 0.0,
                "Q_gut": 0.0}

    def drive(self, scenario: c.Scenario | None, inputs: Inputs) -> Any:
        schedule = meals(scenario, inputs, self.time_scale_s)
        external = inputs.get("Ra")
        return lambda t: {"dose": last_dose(t, schedule), "Ra": external}

    def impulses(self, scenario: c.Scenario | None, inputs: Inputs) -> list[Impulse]:
        if inputs.get("Ra") is not None:
            return []
        return [(t, {"Q_sto1": mg}) for t, mg in meals(scenario, inputs, self.time_scale_s)]

    def _fluxes(self, y: Array, p: Params, u: Mapping[str, Any]) -> dict[str, float]:
        g_p, g_t, _, i_p, x, _, i_d, i_po, yy, q1, q2, qg = y
        d1, d2, dg, ra_gut, _ = gut_rates(q1, q2, qg, float(u.get("dose", 0.0)), p)
        ra = float(u["Ra"]) if u.get("Ra") is not None else ra_gut
        g = g_p / p["V_G"]
        i = i_p / p["V_I"]
        egp = max(0.0, p["k_p1"] - p["k_p2"] * g_p - p["k_p3"] * i_d - p["k_p4"] * i_po)
        u_id = (p["V_m0"] + p["V_mX"] * x) * g_t / (p["K_m0"] + g_t)
        e = p["k_e1"] * (g_p - p["k_e2"]) if g_p > p["k_e2"] else 0.0
        dgp = egp + ra - p["F_cns"] - e - p["k_1"] * g_p + p["k_2"] * g_t
        s_po = yy + p["K"] * max(dgp, 0.0) / p["V_G"] + p["S_b"]
        s = p["gamma"] * i_po
        he = -p["m_5"] * s + p["m_6"]
        m_3 = he * p["m_1"] / (1 - he)
        return {"g": g, "i": i, "egp": egp, "u_id": u_id, "e": e, "ra": ra, "dgp": dgp,
                "s_po": s_po, "s": s, "m_3": m_3, "d1": d1, "d2": d2,
                "dg": dg if u.get("Ra") is None else 0.0}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        _, g_t, i_l, i_p, x, i_1, i_d, i_po, yy, *_ = y
        fl = self._fluxes(y, p, u)
        threshold = -p["S_b"] / p["beta"] + p["G_b"]
        dy = (-p["alpha"] * (yy - p["beta"] * (fl["g"] - p["G_b"])) if fl["g"] >= threshold
              else -p["alpha"] * yy - p["alpha"] * p["S_b"])
        return [
            fl["dgp"],
            -fl["u_id"] + p["k_1"] * y[0] - p["k_2"] * g_t,
            -(p["m_1"] + fl["m_3"]) * i_l + p["m_2"] * i_p + fl["s"],
            -(p["m_2"] + p["m_4"]) * i_p + p["m_1"] * i_l,
            -p["p_2U"] * x + p["p_2U"] * (fl["i"] - p["I_b"]),
            -p["k_i"] * (i_1 - fl["i"]),
            -p["k_i"] * (i_d - i_1),
            -p["gamma"] * i_po + fl["s_po"],
            dy, fl["d1"], fl["d2"], fl["dg"],
        ]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        fl = self._fluxes(y, p, u)
        return {"glucose": fl["g"] * MGDL_TO_MMOLL, "glucose_mgdl": fl["g"], "insulin": fl["i"],
                "insulin_secretion": fl["s"],
                "EGP": fl["egp"], "utilisation": p["F_cns"] + fl["u_id"], "Ra": fl["ra"],
                "renal_excretion": fl["e"]}

    def events(self, t: Array, series: Mapping[str, Array],
               p: Params) -> list[c.TrajectoryEvent]:
        g = series.get("glucose")
        if g is None or len(g) == 0:
            return []
        peak = int(np.argmax(g))
        return [c.TrajectoryEvent(t=float(t[peak]), kind="glucose_peak",
                                  detail={"glucose": float(g[peak]), "unit": "mmol/L"})]


@dataclass(frozen=True)
class FsigtFit:
    p1: float
    p2: float
    p3: float

    @property
    def glucose_effectiveness(self) -> float:
        return self.p1

    @property
    def insulin_sensitivity(self) -> float:
        return self.p3 / self.p2


class MinimalModel(OdeModel):
    """Bergman combined minimal model (glucose, remote insulin, plasma insulin)."""

    spec = ModelSpec(
        model_id="ahdt.endocrine.glucose_insulin_and_metabolic_regulation.minimal_model",
        twin=DTKind.ENDOCRINE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Insulin sensitivity and glucose effectiveness from an FSIGT",
        instances=("UBERON:0001264",),
        outputs=(Port("glucose_mgdl", "mg/dL"), Port("insulin", "u[IU]/mL"),
                 Port("remote_insulin", "/min")),
        validity={"test": "frequently sampled intravenous glucose tolerance test"},
        obs_map={})
    params_stem = "minimal_model"
    state_names = ("G", "X", "I")
    time_scale_s = 60.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {"G": p["G_0"], "X": 0.0, "I": p["I_0"]}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        g, x, i = y
        if callable(u.get("insulin_data")):
            i = float(u["insulin_data"](t))
        secretion = p["gamma"] * (g - p["h"]) * t if g > p["h"] else 0.0
        return [-p["p1"] * (g - p["G_b"]) - x * g,
                p["p3"] * (i - p["I_b"]) - p["p2"] * x,
                -p["n"] * y[2] + secretion]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        return {"glucose_mgdl": float(y[0]), "remote_insulin": float(y[1]),
                "insulin": float(y[2])}

    def fit_glucose(self, t_min: Sequence[float], glucose: Sequence[float],
                    insulin: Sequence[float], *, g0: float | None = None,
                    censor_before_min: float = 8.0, relative_sd: float = 0.015) -> FsigtFit:
        """Least-squares fit of p1, p2, p3 to FSIGT glucose with insulin as a forcing
        function interpolated from the data (the glucose minimal model of Pacini and
        Bergman 1986). G_0 defaults to the peak glucose; G_b and I_b are the last samples.
        Samples before `censor_before_min` are not fitted because mixing is incomplete."""
        t = np.asarray(t_min, dtype=float)
        g_obs = np.asarray(glucose, dtype=float)
        i_obs = np.asarray(insulin, dtype=float)
        g0 = float(g_obs.max()) if g0 is None else g0
        gb, ib = float(g_obs[-1]), float(i_obs[-1])
        mask = t >= censor_before_min
        weights = 1.0 / (relative_sd * g_obs[mask])

        def interp(x: float) -> float:
            return float(np.interp(x, t, i_obs))

        def residuals(theta: Array) -> Array:
            p = {"p1": theta[0], "p2": theta[1], "p3": theta[2] * 1e-5, "G_b": gb, "I_b": ib,
                 "gamma": 0.0, "h": 0.0, "n": 0.0}
            u = {"insulin_data": interp}
            ys = self.integrate(p, np.array([g0, 0.0, ib]), t[mask], lambda _t: u)
            res: Array = (ys[:, 0] - g_obs[mask]) * weights
            return res

        sol = least_squares(residuals, np.array([0.03, 0.02, 1.0]), bounds=(1e-9, np.inf),
                            x_scale="jac")
        return FsigtFit(p1=float(sol.x[0]), p2=float(sol.x[1]), p3=float(sol.x[2]) * 1e-5)
