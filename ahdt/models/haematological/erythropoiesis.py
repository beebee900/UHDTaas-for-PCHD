"""Bone marrow and erythrocytes (inventory item 10).

Red cells are released from a two-stage marrow precursor chain whose production is
proportional to the erythropoietin level relative to baseline (raised to `epo_gain`).
Erythropoietin follows haemoglobin by the log-linear regression of Semba et al. (2001).
Red cells are lost by senescence (lifespan) and by haemolysis: a direct haemolysis rate,
and the rupture of parasitised cells, one asexual cycle after invasion, at the
parasitaemia reported by the Immune twin. At baseline the production balances senescence.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from ahdt.models.reference import person_value
from atra import contracts as c
from atra.connectors import DTKind


def epo(hb_g_dl: float, p: Params) -> float:
    return float(10 ** (p["epo_intercept"] - p["epo_slope"] * hb_g_dl * 10.0))


class ErythropoiesisModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.haematological.bone_marrow_and_erythrocytes",
        twin=DTKind.HAEMATOLOGICAL, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Haemoglobin trajectory under haemolysis, blood loss and recovery",
        instances=("UBERON:0000178", "UBERON:0002371"),
        inputs=(Port("hb0", "g/dL", "field:718-7"),
                Port("haemolysis_rate", "10*6/uL/d", "input:condition"),
                Port("parasitaemia", "%", "connector:HaemolysisConnector#parasitaemia"),
                Port("lifespan_factor", "1", "input:condition"),
                Port("marrow_suppression", "1", "input:condition"),
                Port("spo2", "%", "field:59408-5"),
                Port("pao2", "mm[Hg]", "field:2703-7")),
        outputs=(Port("hb", "g/dL"), Port("rbc", "10*6/uL"), Port("haematocrit", "%"),
                 Port("epo", "[IU]/L"), Port("erythropoiesis_rate", "10*6/uL/d"),
                 Port("o2_content", "mL/dL")),
        validity={"epo_regression": "derived in infants; see the parameter source"},
        explainers=("sensitivity.local", "counterfactual.scenario"),
        obs_map={"718-7": "hb"})
    params_stem = "erythropoiesis"
    state_names = ("RBC", "P1", "P2")
    time_scale_s = 86400.0

    def _baseline(self, p: Params, u: Mapping[str, Any]) -> tuple[float, float]:
        hb0 = float(person_value(u, "hb0"))
        rbc0 = hb0 / p["mch"] * 10.0
        return rbc0, rbc0 / p["rbc_lifespan"]

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        rbc0, prod0 = self._baseline(p, inputs)
        stage = prod0 * p["maturation_days"] / 2
        return {"RBC": rbc0, "P1": stage, "P2": stage}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        rbc, p1, p2 = y
        rbc0, prod0 = self._baseline(p, u)
        hb = rbc * p["mch"] / 10.0
        relative = epo(hb, p) / epo(rbc0 * p["mch"] / 10.0, p)
        production = (prod0 * relative ** p["epo_gain"]
                      * (1 - float(u.get("marrow_suppression", 0.0))))
        k = 2.0 / p["maturation_days"]
        lifespan = p["rbc_lifespan"] * float(u.get("lifespan_factor", 1.0))
        rupture = float(u.get("parasitaemia", 0.0)) / 100.0 * rbc / p["malaria_cycle_days"]
        return [k * p2 - rbc / lifespan - float(u.get("haemolysis_rate", 0.0)) - rupture,
                production - k * p1, k * p1 - k * p2]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        rbc = float(y[0])
        hb = rbc * p["mch"] / 10.0
        out = {"hb": hb, "rbc": rbc, "haematocrit": rbc * p["mcv"] / 10.0, "epo": epo(hb, p),
               "erythropoiesis_rate": 2.0 / p["maturation_days"] * float(y[2])}
        if u.get("spo2") is not None and u.get("pao2") is not None:
            out["o2_content"] = (p["hufner"] * hb * float(u["spo2"]) / 100.0
                                 + p["o2_solubility"] * float(u["pao2"]))
        return out
