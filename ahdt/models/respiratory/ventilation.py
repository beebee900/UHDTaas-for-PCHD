"""Ventilation control (inventory item 2): a chemoreflex controller.

Minute ventilation relaxes towards a target set by a central CO2 term, linear in the
arterial PCO2 above its set point, and a peripheral O2 term proportional to the carotid
chemoreceptor firing above its resting rate. The chemoreceptor static curve is the
sigmoid of Ursino and Magosso (2000) with first-order dynamics. The arterial gases come
from the gas exchange model at the current ventilation, which closes the loop.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from ahdt.models.reference import person_value
from ahdt.models.respiratory.gas_exchange import GasExchangeModel, exchange
from atra import contracts as c
from atra.connectors import DTKind


def chemoreceptor(pao2: float, p: Params) -> float:
    x = math.exp((pao2 - p["pao2_n"]) / p["k_ac"])
    return (p["f_ac_max"] + p["f_ac_min"] * x) / (1 + x)


class VentilationControlModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.respiratory.ventilation_control",
        twin=DTKind.RESPIRATORY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Ventilatory response to hypoxia and hypercapnia",
        inputs=(Port("fio2", "1", "input:scenario"), Port("vco2", "mL/min", "input:metabolism"),
                Port("respiratory_rate", "/min", "field:9279-1"),
                Port("shunt_fraction", "1", "facet:UBERON:0002048/gas_exchange#shunt_fraction")),
        outputs=(Port("minute_ventilation", "L/min"), Port("paco2", "mm[Hg]"),
                 Port("pao2", "mm[Hg]"), Port("chemoreceptor_activity", "Hz")),
        depends_on=(("ahdt.respiratory.lungs_and_gas_exchange", "1.0.0"),),
        explainers=("counterfactual.scenario",))
    params_stem = "ventilation"
    state_names = ("VE", "f_ac")

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.lung = GasExchangeModel().base_params()

    def _gases(self, ve: float, u: Mapping[str, Any]) -> dict[str, float]:
        rr = float(person_value(u, "respiratory_rate"))
        return exchange(self.lung, {**u, "respiratory_rate": rr,
                                    "tidal_volume": max(ve * 1000.0 / rr, 1.0)})

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        gases = self._gases(p["ve_rest"], inputs)
        return {"VE": p["ve_rest"], "f_ac": chemoreceptor(gases["pao2"], p)}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        ve, f_ac = y
        gases = self._gases(float(ve), u)
        resting = chemoreceptor(self._gases(p["ve_rest"], {})["pao2"], p)
        target = (p["ve_rest"] + p["central_gain"] * (gases["paco2"] - p["paco2_set"])
                  + p["peripheral_gain"] * (f_ac - resting))
        return [(max(target, 0.5) - ve) / p["tau_ve"],
                (chemoreceptor(gases["pao2"], p) - f_ac) / p["tau_c"]]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        gases = self._gases(float(y[0]), u)
        return {"minute_ventilation": float(y[0]), "paco2": gases["paco2"],
                "pao2": gases["pao2"], "chemoreceptor_activity": float(y[1])}
