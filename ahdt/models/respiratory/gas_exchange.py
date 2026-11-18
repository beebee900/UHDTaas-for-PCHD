"""Lungs and gas exchange (inventory item 2).

- Alveolar ventilation from tidal volume, dead space and rate.
- Arterial CO2 tension from the alveolar ventilation equation.
- Alveolar O2 tension from the simplified alveolar gas equation.
- Arterial O2 content from the shunt equation, mixing end-capillary blood at the alveolar
  O2 tension with mixed venous blood; the arterial O2 tension is found by inverting the
  content curve, which uses the Severinghaus (1979) dissociation curve.
- Single-compartment mechanics: peak airway pressure for the tidal volume and inspiratory
  flow.

The shunt fraction is calibrated so that the computed SpO2 matches the observed SpO2.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from scipy.optimize import brentq

from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from ahdt.models.reference import person_value
from atra import contracts as c
from atra.connectors import DTKind

SPO2_CODES = ("59408-5", "2708-6", "59417-6")


def saturation(po2: float) -> float:
    """Severinghaus (1979) standard O2 dissociation curve, fraction saturated."""
    po2 = max(po2, 1e-6)
    return 1.0 / (23400.0 / (po2 ** 3 + 150.0 * po2) + 1.0)


def content(po2: float, hb: float, p: Params) -> float:
    """O2 content in mL/dL for a haemoglobin in g/dL."""
    return p["hufner"] * hb * saturation(po2) + p["o2_solubility"] * po2


def exchange(p: Params, u: Mapping[str, Any]) -> dict[str, float]:
    fio2 = float(u.get("fio2", 0.21))
    rr = float(person_value(u, "respiratory_rate"))
    vt = float(person_value(u, "tidal_volume"))
    hb = float(person_value(u, "hb"))
    co = float(person_value(u, "cardiac_output"))
    vo2 = float(u.get("vo2", p["vo2"]))
    vco2 = float(u.get("vco2", p["vco2"]))
    shunt = min(max(float(u.get("shunt_fraction", p["shunt_fraction"])), 0.0), 0.95)
    va = max((vt - p["dead_space"]) * rr / 1000.0, 1e-3)
    paco2 = p["k_paco2"] * vco2 / va
    pao2_alv = max(fio2 * (p["p_atm"] - p["p_h2o"]) - paco2 / p["rq"], 1.0)
    c_cap = content(pao2_alv, hb, p)
    c_art = c_cap - shunt / (1 - shunt) * vo2 / (10.0 * co)
    pao2 = brentq(lambda x: content(x, hb, p) - c_art, 1e-3, pao2_alv) if c_art > 0 else 0.0
    flow = vt / 1000.0 / float(u.get("inspiratory_time", p["inspiratory_time"]))
    return {"pao2": pao2, "paco2": paco2, "PAO2": pao2_alv, "aa_gradient": pao2_alv - pao2,
            "spo2": 100.0 * saturation(pao2), "cao2": c_art, "shunt_fraction": shunt,
            "alveolar_ventilation": va, "minute_ventilation": vt * rr / 1000.0,
            "peak_airway_pressure": vt / 1000.0 / p["compliance"]
            + p["airway_resistance"] * flow}


class GasExchangeModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.respiratory.lungs_and_gas_exchange",
        twin=DTKind.RESPIRATORY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Arterial blood gases and oxygen saturation from ventilation and perfusion",
        instances=("UBERON:0002048",),
        inputs=(Port("respiratory_rate", "/min", "field:9279-1"),
                Port("tidal_volume", "mL", "input:ventilation"),
                Port("fio2", "1", "input:scenario"),
                Port("hb", "g/dL", "facet:UBERON:0000178/oxygen_carriage#hb"),
                Port("cardiac_output", "L/min",
                     "facet:UBERON:0000948/haemodynamics#cardiac_output")),
        outputs=(Port("pao2", "mm[Hg]"), Port("paco2", "mm[Hg]"), Port("PAO2", "mm[Hg]"),
                 Port("aa_gradient", "mm[Hg]"), Port("spo2", "%"), Port("cao2", "mL/dL"),
                 Port("shunt_fraction", "1"), Port("alveolar_ventilation", "L/min"),
                 Port("minute_ventilation", "L/min"), Port("peak_airway_pressure", "cm[H2O]")),
        validity={"altitude": "sea level", "state": "steady"},
        explainers=("sensitivity.local", "counterfactual.scenario"),
        obs_map=dict.fromkeys(SPO2_CODES, "spo2"))
    params_stem = "gas_exchange"

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        return exchange(p, {**{k: v for k, v in state.items()
                               if k in ("shunt_fraction",)}, **inputs})

    async def calibrate(self, state: c.InstanceRecord, obs: Sequence[c.ObservationRecord], *,
                        inputs: Inputs | None = None) -> c.InstanceRecord:
        """Set the shunt fraction that reproduces the latest observed SpO2."""
        from ahdt.models.base import _latest_by_output

        latest = _latest_by_output(self.spec, obs).get("spo2")
        if latest is None:
            return state
        when, target = latest
        p = self.parameters(state)
        u = dict(inputs or {})

        def gap(s: float) -> float:
            return exchange(p, {**u, "shunt_fraction": s})["spo2"] - target

        lo, hi = 0.0, 0.6
        shunt = lo if gap(lo) <= 0 else (hi if gap(hi) >= 0 else brentq(gap, lo, hi))
        values = exchange(p, {**u, "shunt_fraction": shunt})
        return state.model_copy(update={"params": {**state.params, "shunt_fraction": shunt},
                                        "state": {**state.state, **values},
                                        "last_assimilated": when})
