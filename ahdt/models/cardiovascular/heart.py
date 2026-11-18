"""Heart chambers and valves (inventory item 1).

The Smith et al. (2004) closed-loop minimal haemodynamic model: two time-varying elastance
ventricles coupled through the septum and pericardium, inertial "open on pressure, close
on flow" valves, and elastance vessels for the aorta, vena cava, pulmonary artery and
pulmonary vein. The published model has no atria; atrial filling is represented by the
venous elastances.

Each beat is integrated by a compiled fixed-step Runge-Kutta kernel, with the septal
volume solved by Newton iteration at every evaluation. Beats repeat until consecutive
beats agree, and the model reports beat-averaged haemodynamics. Over long horizons it
runs quasi-statically: one periodic solution per distinct set of inputs.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
from numba import njit

from ahdt.models.arrays import Array
from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from atra import contracts as c
from atra.connectors import DTKind

STATES = ("V_lv", "V_rv", "V_pa", "V_pu", "V_ao", "V_vc", "Q_mt", "Q_av", "Q_tc", "Q_pv")
PNAMES = ("R_mt", "R_av", "R_tc", "R_pv", "R_pul", "R_sys", "L_tc", "L_pv", "L_mt", "L_av",
          "P_th", "A", "B", "C", "period", "P_0_pcd", "V_0_pcd", "lambda_pcd", "E_es_lvf",
          "V_d_lvf", "P_0_lvf", "lambda_lvf", "V_0_lvf", "E_es_rvf", "V_d_rvf", "P_0_rvf",
          "lambda_rvf", "V_0_rvf", "E_es_spt", "V_d_spt", "P_0_spt", "lambda_spt", "V_0_spt",
          "E_es_pa", "V_d_pa", "E_es_pu", "V_d_pu", "E_es_ao", "V_d_ao", "E_es_vc", "V_d_vc")
(R_MT, R_AV, R_TC, R_PV, R_PUL, R_SYS, L_TC, L_PV, L_MT, L_AV, P_TH, A_, B_, C_, PERIOD,
 P0_PCD, V0_PCD, LAM_PCD, E_LVF, VD_LVF, P0_LVF, LAM_LVF, V0_LVF, E_RVF, VD_RVF, P0_RVF,
 LAM_RVF, V0_RVF, E_SPT, VD_SPT, P0_SPT, LAM_SPT, V0_SPT, E_PA, VD_PA, E_PU, VD_PU, E_AO,
 VD_AO, E_VC, VD_VC) = range(len(PNAMES))
STEPS_PER_BEAT = 3000
SAMPLES = 301
MAX_BEATS = 60
TOLERANCE = 1e-4


@njit(cache=True)
def _balance(v: float, e: float, v_lv: float, v_rv: float, q: Array) -> tuple[float, float]:
    """Septal pressure balance and its derivative with respect to the septal volume."""
    a = math.exp(q[LAM_SPT] * (v - q[V0_SPT]))
    b = math.exp(q[LAM_LVF] * (v_lv - v))
    d = math.exp(q[LAM_RVF] * (v_rv + v))
    f = (e * q[E_SPT] * (v - q[VD_SPT]) + (1 - e) * q[P0_SPT] * (a - 1)
         - e * q[E_LVF] * (v_lv - v) - (1 - e) * q[P0_LVF] * (b - 1)
         + e * q[E_RVF] * (v_rv + v) + (1 - e) * q[P0_RVF] * (d - 1))
    df = (e * q[E_SPT] + (1 - e) * q[P0_SPT] * q[LAM_SPT] * a + e * q[E_LVF]
          + (1 - e) * q[P0_LVF] * q[LAM_LVF] * b + e * q[E_RVF]
          + (1 - e) * q[P0_RVF] * q[LAM_RVF] * d)
    return f, df


@njit(cache=True)
def _septum(e: float, v_lv: float, v_rv: float, q: Array, guess: float) -> float:
    """Newton solve of the septal balance, which is monotonic in the septal volume."""
    v = guess
    for _ in range(50):
        f, df = _balance(v, e, v_lv, v_rv, q)
        step = f / df
        v -= step
        if abs(step) < 1e-10:
            break
    return v


@njit(cache=True)
def _deriv(t: float, y: Array, q: Array, guess: float,
           dy: Array) -> tuple[float, float, float]:
    """Fill `dy`; return (septal volume, aortic pressure, left ventricular pressure)."""
    tau = t % q[PERIOD]
    e = q[A_] * math.exp(-q[B_] * (tau - q[C_]) ** 2)
    v_lv, v_rv, v_pa, v_pu, v_ao, v_vc = y[0], y[1], y[2], y[3], y[4], y[5]
    q_mt, q_av, q_tc, q_pv = y[6], y[7], y[8], y[9]
    v_spt = _septum(e, v_lv, v_rv, q, guess)
    v_lvf, v_rvf = v_lv - v_spt, v_rv + v_spt
    p_peri = q[P0_PCD] * (math.exp(q[LAM_PCD] * (v_lv + v_rv - q[V0_PCD])) - 1) + q[P_TH]
    p_lv = (e * q[E_LVF] * (v_lvf - q[VD_LVF])
            + (1 - e) * q[P0_LVF] * (math.exp(q[LAM_LVF] * (v_lvf - q[V0_LVF])) - 1) + p_peri)
    p_rv = (e * q[E_RVF] * (v_rvf - q[VD_RVF])
            + (1 - e) * q[P0_RVF] * (math.exp(q[LAM_RVF] * (v_rvf - q[V0_RVF])) - 1) + p_peri)
    p_pa = q[E_PA] * (v_pa - q[VD_PA]) + q[P_TH]
    p_pu = q[E_PU] * (v_pu - q[VD_PU]) + q[P_TH]
    p_ao = q[E_AO] * (v_ao - q[VD_AO])
    p_vc = q[E_VC] * (v_vc - q[VD_VC])
    q_sys = (p_ao - p_vc) / q[R_SYS]
    q_pul = (p_pa - p_pu) / q[R_PUL]
    dy[0] = 0.0 if (q_mt < 0 and q_av < 0) else (-q_av if q_mt < 0 else (q_mt if q_av < 0
                                                                       else q_mt - q_av))
    dy[1] = 0.0 if (q_tc < 0 and q_pv < 0) else (-q_pv if q_tc < 0 else (q_tc if q_pv < 0
                                                                       else q_tc - q_pv))
    dy[2] = -q_pul if q_pv < 0 else q_pv - q_pul
    dy[3] = q_pul if q_mt < 0 else q_pul - q_mt
    dy[4] = -q_sys if q_av < 0 else q_av - q_sys
    dy[5] = q_sys if q_tc < 0 else q_sys - q_tc
    dy[6] = 0.0 if (p_pu - p_lv < 0 and q_mt < 0) else (p_pu - p_lv - q_mt * q[R_MT]) / q[L_MT]
    dy[7] = 0.0 if (p_lv - p_ao < 0 and q_av < 0) else (p_lv - p_ao - q_av * q[R_AV]) / q[L_AV]
    dy[8] = 0.0 if (p_vc - p_rv < 0 and q_tc < 0) else (p_vc - p_rv - q_tc * q[R_TC]) / q[L_TC]
    dy[9] = 0.0 if (p_rv - p_pa < 0 and q_pv < 0) else (p_rv - p_pa - q_pv * q[R_PV]) / q[L_PV]
    return v_spt, p_ao, p_lv


@njit(cache=True)
def _beat(y0: Array, q: Array) -> tuple[Array, Array, Array,
                                                  Array]:
    """One beat by fixed-step fourth-order Runge-Kutta, sampled at SAMPLES points."""
    n = y0.shape[0]
    h = q[PERIOD] / STEPS_PER_BEAT
    every = STEPS_PER_BEAT // (SAMPLES - 1)
    ys = np.empty((SAMPLES, n))
    p_ao = np.empty(SAMPLES)
    p_lv = np.empty(SAMPLES)
    y = y0.copy()
    k1, k2, k3, k4, tmp = (np.empty(n), np.empty(n), np.empty(n), np.empty(n), np.empty(n))
    guess = 0.0
    for i in range(STEPS_PER_BEAT + 1):
        t = i * h
        guess, pa, pl = _deriv(t, y, q, guess, k1)
        if i % every == 0:
            j = i // every
            ys[j] = y
            p_ao[j] = pa
            p_lv[j] = pl
        if i == STEPS_PER_BEAT:
            break
        for k in range(n):
            tmp[k] = y[k] + 0.5 * h * k1[k]
        _deriv(t + 0.5 * h, tmp, q, guess, k2)
        for k in range(n):
            tmp[k] = y[k] + 0.5 * h * k2[k]
        _deriv(t + 0.5 * h, tmp, q, guess, k3)
        for k in range(n):
            tmp[k] = y[k] + h * k3[k]
        _deriv(t + h, tmp, q, guess, k4)
        for k in range(n):
            y[k] += h / 6.0 * (k1[k] + 2 * k2[k] + 2 * k3[k] + k4[k])
    return ys, p_ao, p_lv, y


def effective(p: Params, inputs: Inputs) -> dict[str, float]:
    """Parameters after the autonomic and coupled inputs: heart rate sets the period,
    contractility scales the free-wall end-systolic elastances, and the resistance factor
    scales the systemic resistance."""
    q = dict(p)
    if inputs.get("heart_rate"):
        q["period"] = 60.0 / float(inputs["heart_rate"])
    contractility = float(inputs.get("contractility_factor", 1.0))
    q["E_es_lvf"] = p["E_es_lvf"] * contractility
    q["E_es_rvf"] = p["E_es_rvf"] * contractility
    q["R_sys"] = p["R_sys"] * float(inputs.get("resistance_factor", 1.0))
    return q


def periodic_beat(p: Params, y0: Array) -> tuple[Array, Array, Array,
                                                     Array, Array, int]:
    """Integrate whole beats until the start-of-beat volumes repeat.

    Returns the sample times, states, aortic and left ventricular pressures of the last
    beat, the start state of the next beat, and the number of beats integrated.
    """
    q = np.array([p[name] for name in PNAMES])
    y = np.asarray(y0, dtype=float)
    for beat in range(1, MAX_BEATS + 1):
        ys, p_ao, p_lv, end = _beat(y, q)
        change = np.max(np.abs(end[:6] - y[:6]) / np.maximum(np.abs(y[:6]), 1.0))
        y = end
        if change < TOLERANCE and beat >= 2:
            break
    grid: Array = np.linspace(0.0, p["period"], SAMPLES)
    final: Array = y
    return grid, ys, p_ao, p_lv, final, beat


def haemodynamics(p: Params, grid: Array, ys: Array, p_ao: Array,
                  p_lv: Array) -> dict[str, float]:
    period = p["period"]
    v_lv = ys[:, 0]
    sv = float(np.trapezoid(np.clip(ys[:, 7], 0.0, None), grid))
    edv, esv = float(v_lv.max()), float(v_lv.min())
    hr = 60.0 / period
    return {
        "heart_rate": hr, "stroke_volume": sv, "cardiac_output": sv * hr / 1000.0,
        "ejection_fraction": 100.0 * (edv - esv) / edv if edv > 0 else 0.0,
        "lv_edv": edv, "lv_esv": esv, "sbp": float(p_ao.max()), "dbp": float(p_ao.min()),
        "map": float(np.trapezoid(p_ao, grid) / period),
        "lvedp": float(p_lv[int(np.argmax(v_lv))]), "total_volume": float(ys[-1, :6].sum()),
    }


class HeartModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.cardiovascular.heart_chambers_and_valves",
        twin=DTKind.CARDIOVASCULAR, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Beat-averaged cardiac output, arterial pressures and ventricular volumes",
        instances=("UBERON:0000948",),
        inputs=(Port("heart_rate", "/min",
                     "model:ahdt.cardiovascular.baroreflex_regulation#heart_rate"),
                Port("contractility_factor", "1",
                     "model:ahdt.cardiovascular.baroreflex_regulation#contractility_factor"),
                Port("resistance_factor", "1",
                     "model:ahdt.cardiovascular.baroreflex_regulation#resistance_factor")),
        outputs=(Port("cardiac_output", "L/min"), Port("stroke_volume", "mL"),
                 Port("ejection_fraction", "%"), Port("heart_rate", "/min"),
                 Port("sbp", "mm[Hg]"), Port("dbp", "mm[Hg]"), Port("map", "mm[Hg]"),
                 Port("lv_edv", "mL"), Port("lv_esv", "mL"), Port("lvedp", "mm[Hg]")),
        validity={"population": "adult at rest"},
        explainers=("sensitivity.local", "counterfactual.scenario"),
        obs_map={"8867-4": "heart_rate", "8480-6": "sbp", "8462-4": "dbp"})
    params_stem = "heart"

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {"V_lv": p["V_lv0"], "V_rv": p["V_rv0"], "V_pa": p["V_pa0"], "V_pu": p["V_pu0"],
                "V_ao": p["V_ao0"], "V_vc": p["V_vc0"], "Q_mt": p["Q_mt0"], "Q_av": 0.0,
                "Q_tc": p["Q_tc0"], "Q_pv": 0.0}

    def _start(self, p: Params, state: Mapping[str, Any]) -> Array:
        initial = self.initial_state(p, {})
        return np.array([float(state.get(n, initial[n])) for n in STATES])

    def beat(self, p: Params, state: Mapping[str, Any],
             inputs: Inputs) -> tuple[dict[str, float], dict[str, float]]:
        q = effective(p, inputs)
        grid, ys, p_ao, p_lv, end, _ = periodic_beat(q, self._start(p, state))
        return (haemodynamics(q, grid, ys, p_ao, p_lv),
                dict(zip(STATES, (float(v) for v in end), strict=True)))

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        values, _ = self.beat(p, state, inputs)
        values.pop("total_volume")
        return values

    def series(self, p: Params, state: Mapping[str, Any], t_s: Array, u: Any, *,
               param_path: Any = None, impulses: Any = ()) -> dict[str, Array]:
        """Quasi-static run: one periodic solution per distinct set of inputs."""
        current = dict(state)
        cache: dict[tuple[tuple[str, float], ...], dict[str, Any]] = {}
        out: dict[str, list[float]] = {port.name: [] for port in self.spec.outputs}
        for t in t_s:
            inputs = u(float(t))
            q = param_path(float(t), p) if param_path else p
            key = tuple(sorted((k, round(float(v), 6)) for k, v in {**inputs, **q}.items()
                               if isinstance(v, int | float)))
            if key not in cache:
                cache[key], current = self.beat(q, current, inputs)
            for name in out:
                out[name].append(float(cache[key][name]))
        return {k: np.array(v) for k, v in out.items()}
