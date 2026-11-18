"""Whole-body PBPK (design 04, 4.5.3; design 01, 1.3).

The OSP Suite route (`ospsuite` through R and `rpy2`) is used when it is installed. Otherwise
this generic flow-limited model runs with the same compartments: arterial and venous blood,
lung, heart, brain, kidney, liver, splanchnic bed (gut wall, spleen, pancreas), muscle,
adipose tissue, skin, bone and the remaining tissues. Organ masses and blood flows are the
ICRP Publication 89 reference values. Every tissue shares one partition coefficient that
is scaled so the steady-state volume of distribution equals the drug's labelled value.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import Any

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.base import Impulse, Inputs, ModelSpec, OdeModel, Params, Port
from atra import contracts as c
from atra.connectors import DTKind

TISSUES = ("heart", "brain", "kidney", "liver", "splanchnic", "muscle", "adipose", "skin",
           "bone", "rest")
STATES = ("gut", "art", "ven", "lung", *TISSUES, "eliminated", "unabsorbed")
DRUGS = {"A10BA02": ("metformin", "oral"), "J01DD04": ("ceftriaxone", "iv")}
ROUTE_STATE = {"oral": "gut", "iv": "ven"}
HOURS_PER_MIN = 60.0


def drug_properties(p: Params, drug: str) -> dict[str, float]:
    keys = ("bioavailability", "vss", "renal_clearance", "nonrenal_clearance", "ka")
    return {k: p[f"{drug}_{k}"] for k in keys if f"{drug}_{k}" in p}


@lru_cache(maxsize=256)
def _physiology(key: tuple[tuple[str, float], ...], female: bool, weight_kg: float
                ) -> tuple[dict[str, float], dict[str, float], float, float]:
    """Compartment volumes (L), flows (L/h), arterial and venous volumes (L)."""
    p = dict(key)
    sx = "f" if female else "m"
    scale = weight_kg / (p[f"total_mass_{sx}"] / 1000.0)
    density = p["tissue_density"]
    volumes = {t: p[f"mass_{t}_{sx}"] / 1000.0 / density * scale
               for t in ("lung", *TISSUES) if f"mass_{t}_{sx}" in p}
    listed = sum(p[f"mass_{t}_{sx}"] for t in volumes) + p[f"blood_mass_{sx}"]
    volumes["rest"] = max(p[f"total_mass_{sx}"] - listed, 0.0) / 1000.0 / density * scale
    co = p[f"cardiac_output_{sx}"] * 60.0 * scale ** p["cardiac_output_exponent"]
    flows = {t: p[f"flow_{t}_{sx}"] / 100.0 * co for t in TISSUES if f"flow_{t}_{sx}" in p}
    flows["rest"] = co - sum(flows.values())
    flows["lung"] = co
    blood = p[f"blood_volume_{sx}"] * scale
    return (volumes, flows, blood * p["arterial_blood_fraction"] / 100.0,
            blood * p["venous_blood_fraction"] / 100.0)


class WholeBodyPbpkModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.whole_body.whole_body_pbpk",
        twin=DTKind.WHOLE_BODY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Plasma and organ concentrations of metformin and ceftriaxone after a dose",
        inputs=(Port("body_weight", "kg", "field:29463-7"),
                Port("female", "1", "input:demographics"),
                Port("egfr", "mL/min", "facet:UBERON:0002113/renal_function#egfr"),
                Port("clearance_factor", "1", "facet:UBERON:0002107/clearance#clearance_factor"),
                Port("drug", "{atc}", "input:drug")),
        outputs=(Port("plasma_concentration", "mg/L"), Port("liver_concentration", "mg/L"),
                 Port("kidney_concentration", "mg/L"), Port("brain_concentration", "mg/L"),
                 Port("muscle_concentration", "mg/L"), Port("amount_in_body", "mg"),
                 Port("eliminated_amount", "mg"), Port("unabsorbed_amount", "mg")),
        explainers=("sensitivity.local",),
        fidelity_note="Generic flow-limited PBPK with ICRP 89 reference physiology; the OSP "
                      "Suite backend is not installed. One tissue partition coefficient per "
                      "drug, scaled to the labelled volume of distribution. The simulated "
                      "metformin peak and half-life differ from the label values; the "
                      "validation record states both, and the parameters are not tuned to "
                      "close the gap.")
    params_stem = "pbpk"
    state_names = STATES
    time_scale_s = 3600.0
    method = "LSODA"

    def _setup(self, p: Params, u: Mapping[str, Any]
               ) -> tuple[dict[str, float], dict[str, float], float, float, dict[str, float],
                          float, float, float]:
        female = bool(u.get("female", 0))
        sx = "f" if female else "m"
        weight = float(u.get("body_weight", p[f"total_mass_{sx}"] / 1000.0))
        key = tuple(sorted((k, v) for k, v in p.items()
                           if k.startswith(("mass_", "flow_", "total_", "blood_", "cardiac_",
                                            "arterial_", "venous_", "tissue_"))))
        volumes, flows, v_art, v_ven = _physiology(key, female, weight)
        drug = self.drug_of(u)
        d = drug_properties(p, drug)
        circulating = v_art + v_ven
        kp = max(d["vss"] - circulating, 1e-6) / sum(volumes.values())
        egfr = float(u.get("egfr", p["reference_egfr"]))
        cl_r = d["renal_clearance"] * egfr / p["reference_egfr"]
        cl_nr = d["nonrenal_clearance"] * float(u.get("clearance_factor", 1.0))
        return volumes, flows, v_art, v_ven, d, kp, cl_r, cl_nr

    def drug_of(self, u: Mapping[str, Any]) -> str:
        atc = str(u.get("drug", "A10BA02"))
        return DRUGS[atc][0] if atc in DRUGS else atc

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return dict.fromkeys(STATES, 0.0)

    def drive(self, scenario: c.Scenario | None, inputs: Inputs) -> Any:
        merged = dict(inputs)
        if scenario is not None:
            for block in (scenario.activity, scenario.diet, scenario.environment,
                          scenario.intervention):
                if block:
                    merged.update(block)
            if scenario.drug is not None:
                merged["drug"] = scenario.drug.atc
        return lambda t: merged

    def impulses(self, scenario: c.Scenario | None, inputs: Inputs) -> list[Impulse]:
        if scenario is None or scenario.drug is None:
            return []
        atc = scenario.drug.atc
        if atc not in DRUGS:
            raise KeyError(f"no PBPK parameters for {atc}")
        route = scenario.drug.route if scenario.drug.route in ROUTE_STATE else DRUGS[atc][1]
        return [(float(t), {ROUTE_STATE[route]: scenario.drug.dose_mg})
                for t in scenario.drug.schedule_h]

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        vol, q, v_art, v_ven, d, kp, cl_r, cl_nr = self._setup(p, u)
        a = dict(zip(STATES, y, strict=True))
        c_art, c_ven = a["art"] / v_art, a["ven"] / v_ven
        cv = {t_: a[t_] / (vol[t_] * kp) for t_ in ("lung", *TISSUES)}
        ka = d.get("ka", 0.0)
        absorbed = ka * a["gut"] * d["bioavailability"]
        lost = ka * a["gut"] * (1.0 - d["bioavailability"])
        q_la, q_sp = q["liver"], q["splanchnic"]
        c_in = (q_la * c_art + q_sp * cv["splanchnic"]) / (q_la + q_sp)
        elim_nr = cl_nr * c_in
        elim_r = cl_r * c_art
        out = dict.fromkeys(STATES, 0.0)
        out["gut"] = -ka * a["gut"]
        out["lung"] = q["lung"] * (c_ven - cv["lung"])
        out["art"] = q["lung"] * cv["lung"] - sum(q[t_] * c_art for t_ in TISSUES)
        for t_ in TISSUES:
            if t_ in ("liver", "splanchnic"):
                continue
            out[t_] = q[t_] * (c_art - cv[t_])
        out["kidney"] -= elim_r
        out["splanchnic"] = q_sp * (c_art - cv["splanchnic"]) + absorbed
        out["liver"] = q_la * c_art + q_sp * cv["splanchnic"] - (q_la + q_sp) * cv["liver"] \
            - elim_nr
        venous_return = sum(q[t_] * cv[t_] for t_ in TISSUES if t_ not in ("liver", "splanchnic"))
        out["ven"] = venous_return + (q_la + q_sp) * cv["liver"] - q["lung"] * c_ven
        out["eliminated"] = elim_r + elim_nr
        out["unabsorbed"] = lost
        return [out[s] for s in STATES]

    def observe(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> dict[str, Any]:
        vol, _, _, v_ven, _, _, _, _ = self._setup(p, u)
        a = dict(zip(STATES, y, strict=True))
        bp = p["blood_to_plasma_ratio"]
        return {"plasma_concentration": a["ven"] / v_ven / bp,
                "liver_concentration": a["liver"] / vol["liver"],
                "kidney_concentration": a["kidney"] / vol["kidney"],
                "brain_concentration": a["brain"] / vol["brain"],
                "muscle_concentration": a["muscle"] / vol["muscle"],
                "amount_in_body": float(sum(a[s] for s in STATES
                                            if s not in ("eliminated", "unabsorbed"))),
                "eliminated_amount": a["eliminated"], "unabsorbed_amount": a["unabsorbed"]}

    def events(self, t: Array, series: Mapping[str, Array], p: Params
               ) -> list[c.TrajectoryEvent]:
        conc = series.get("plasma_concentration")
        if conc is None or len(conc) == 0 or float(np.max(conc)) <= 0:
            return []
        i = int(np.argmax(conc))
        return [c.TrajectoryEvent(t=float(t[i]), kind="cmax",
                                  detail={"plasma_concentration_mg_per_L": float(conc[i])})]


def terminal_half_life_h(t_h: Array, conc: Array, tail: float = 0.4) -> float:
    """Half-life from a log-linear fit to the last `tail` fraction of the series."""
    start = int(len(t_h) * (1 - tail))
    slope = np.polyfit(t_h[start:], np.log(conc[start:]), 1)[0]
    return float(math.log(2) / -slope)
