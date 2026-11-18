"""Thermoregulation (inventory item 12): the Gagge two-node model (Gagge et al. 1986).

Core and skin temperatures change with metabolic heat, respiratory loss, dry heat
exchange through clothing and air, and evaporation, under control of skin blood flow,
regulatory sweating and shivering. The model steps once per minute, as in the published
procedure. A fever input raises the core set point.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from ahdt.models.reference import person_value
from atra import contracts as c
from atra.connectors import DTKind

STATE = ("t_core", "t_skin", "m_bl", "alfa", "e_skin", "m")


def p_sat_torr(t: float) -> float:
    return math.exp(18.6686 - 4030.183 / (t + 235.0))


def environment(u: Mapping[str, Any]) -> dict[str, float]:
    return {"tdb": float(person_value(u, "air_temperature")),
            "tr": float(u.get("radiant_temperature", person_value(u, "air_temperature"))),
            "v": max(float(person_value(u, "air_speed")), 0.1),
            "rh": float(person_value(u, "relative_humidity")), "met": float(person_value(u, "met")),
            "clo": float(person_value(u, "clo")), "fever": float(u.get("fever", 0.0))}


def minute(s: list[float], p: Params, u: Mapping[str, Any]) -> tuple[list[float], dict[str, float]]:
    """One minute of the Gagge procedure; returns the new state and the heat terms."""
    e = environment(u)
    t_core, t_skin, m_bl, alfa, e_skin, m = s
    vapour = e["rh"] * p_sat_torr(e["tdb"]) / 100.0
    rm = e["met"] * p["met_factor"]
    r_clo = 0.155 * e["clo"]
    f_a_cl = 1.0 + 0.15 * e["clo"]
    lr = 2.2
    i_cl = 0.45 if e["clo"] > 0 else 1.0
    w_max = 0.59 * e["v"] ** -0.08 if e["clo"] > 0 else 0.38 * e["v"] ** -0.29
    h_cc = max(3.0, 8.600001 * e["v"] ** 0.53)
    if e["met"] > 0.85:
        h_cc = max(h_cc, 5.66 * (e["met"] - 0.85) ** 0.39)
    q_res = 0.0023 * m * (44.0 - vapour)
    c_res = 0.0014 * m * (34.0 - e["tdb"])
    t_cl = t_skin
    h_r = 4.7
    for _ in range(150):
        h_r = 4.0 * 0.95 * 5.6697e-8 * ((t_cl + e["tr"]) / 2.0 + 273.15) ** 3.0 * 0.73
        h_t = h_r + h_cc
        r_a = 1.0 / (f_a_cl * h_t)
        t_op = (h_r * e["tr"] + h_cc * e["tdb"]) / h_t
        new = (r_a * t_skin + r_clo * t_op) / (r_a + r_clo)
        if abs(new - t_cl) <= 0.01:
            t_cl = new
            break
        t_cl = new
    q_sensible = (t_skin - t_op) / (r_a + r_clo)
    hf_cs = (t_core - t_skin) * (5.28 + 1.163 * m_bl)
    s_core = m - hf_cs - q_res - c_res
    s_skin = hf_cs - q_sensible - e_skin
    tc_sk = 0.97 * alfa * p["body_weight"]
    tc_cr = 0.97 * (1 - alfa) * p["body_weight"]
    t_skin += s_skin * p["body_surface_area"] / (tc_sk * 60.0)
    t_core += s_core * p["body_surface_area"] / (tc_cr * 60.0)
    core_set = p["t_core_neutral"] + p["fever_gain"] * e["fever"]
    alfa0 = p["alfa0"]
    body_set = alfa0 * p["t_skin_neutral"] + (1 - alfa0) * core_set
    t_body = alfa * t_skin + (1 - alfa) * t_core
    sk_sig = t_skin - p["t_skin_neutral"]
    warm_sk, cold_sk = max(sk_sig, 0.0), max(-sk_sig, 0.0)
    c_sig = t_core - core_set
    c_warm, c_cold = max(c_sig, 0.0), max(-c_sig, 0.0)
    warm_b = max(t_body - body_set, 0.0)
    m_bl = min(max((p["skin_blood_flow_neutral"] + p["c_dil"] * c_warm)
                   / (1 + p["c_str"] * cold_sk), 0.5), p["max_skin_blood_flow"])
    m_rsw = min(p["c_sw"] * warm_b * math.exp(warm_sk / 10.7), p["max_sweating"])
    e_rsw = 0.68 * m_rsw
    r_ea = 1.0 / (lr * f_a_cl * h_cc)
    r_ecl = r_clo / (lr * i_cl)
    e_max = (p_sat_torr(t_skin) - vapour) / (r_ea + r_ecl) or 0.001
    p_rsw = e_rsw / e_max
    w = 0.06 + 0.94 * p_rsw
    e_diff = w * e_max - e_rsw
    if w > w_max:
        w = w_max
        p_rsw = w_max / 0.94
        e_rsw = p_rsw * e_max
        e_diff = 0.06 * (1.0 - p_rsw) * e_max
    if e_max < 0:
        e_diff, e_rsw, w = 0.0, 0.0, w_max
    e_skin = e_rsw + e_diff
    shivering = 19.4 * cold_sk * c_cold
    m = rm + shivering
    alfa = 0.0417737 + 0.7451833 / (m_bl + 0.585417)
    terms = {"sweat_rate": e_rsw / 0.68, "skin_wettedness": w, "shivering": shivering,
             "skin_blood_flow": m_bl, "evaporative_loss": e_skin}
    return [t_core, t_skin, m_bl, alfa, e_skin, m], terms


class ThermoregulationModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.integumentary.thermoregulation",
        twin=DTKind.INTEGUMENTARY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Core and skin temperature, sweating and shivering in an environment",
        instances=("UBERON:0002097",),
        inputs=(Port("air_temperature", "Cel", "connector:ExposomeConnector#temp_c"),
                Port("relative_humidity", "%", "connector:ExposomeConnector#humidity"),
                Port("air_speed", "m/s", "input:environment"),
                Port("met", "{met}", "input:activity"),
                Port("clo", "{clo}", "input:scenario"),
                Port("fever", "K", "input:condition")),
        outputs=(Port("core_temp", "Cel"), Port("skin_temp", "Cel"),
                 Port("sweat_rate", "g/(m2.h)"), Port("skin_blood_flow", "L/(m2.h)"),
                 Port("shivering", "W/m2"), Port("skin_wettedness", "1")),
        explainers=("counterfactual.scenario",),
        obs_map={"8310-5": "core_temp"})
    params_stem = "thermoregulation"
    state_names = STATE
    time_scale_s = 60.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {"t_core": p["t_core_neutral"], "t_skin": p["t_skin_neutral"],
                "m_bl": p["skin_blood_flow_neutral"], "alfa": p["alfa0"],
                "e_skin": 0.1 * p["met_factor"], "m": p["met_factor"]}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        raise NotImplementedError("the Gagge model steps once per minute; use integrate()")

    def integrate(self, p: Params, y0: Array, t_eval: Array, u: Any, *,
                  param_path: Any = None, impulses: Any = ()) -> Array:
        out = np.empty((len(t_eval), len(STATE)))
        s = [float(v) for v in y0]
        t, j = 0.0, 0
        while j < len(t_eval):
            while j < len(t_eval) and t_eval[j] <= t + 1e-9:
                out[j] = s
                j += 1
            if j < len(t_eval):
                s, _ = minute(s, p, u(t))
                t += 1.0
        return out

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        _, terms = minute([float(v) for v in y], p, u)
        return {"core_temp": float(y[0]), "skin_temp": float(y[1]), **terms}
