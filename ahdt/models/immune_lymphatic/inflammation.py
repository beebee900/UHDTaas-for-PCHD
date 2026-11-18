"""Inflammation (inventory item 9): the Reynolds et al. (2006) reduced model.

States: pathogen P, activated phagocytes N*, tissue damage D and anti-inflammatory
mediators C_A (dimensionless, time in hours). The same model drives the generic
bacterial infection branch of the infection-response model. Antimicrobial treatment
adds a first-order kill rate on P.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Impulse, Inputs, ModelSpec, OdeModel, Params, Port
from atra import contracts as c
from atra.connectors import DTKind


def reynolds_rhs(y: Sequence[float] | Array, p: Params, kill: float = 0.0) -> list[float]:
    pathogen, n_star, damage, c_a = y
    inhibition = 1 + (c_a / p["c_inf"]) ** 2
    f_n = n_star / inhibition
    r = (p["k_nn"] * n_star + p["k_np"] * pathogen + p["k_nd"] * damage) / inhibition
    f_s = f_n ** 6 / (p["x_dn"] ** 6 + f_n ** 6)
    g = (n_star + p["k_cnd"] * damage) / inhibition
    return [
        p["k_pg"] * pathogen * (1 - pathogen / p["p_inf"])
        - p["k_pm"] * p["s_m"] * pathogen / (p["mu_m"] + p["k_mp"] * pathogen)
        - p["k_pn"] * f_n * pathogen - kill * pathogen,
        p["s_nr"] * r / (p["mu_nr"] + r) - p["mu_n"] * n_star,
        p["k_dn"] * f_s - p["mu_d"] * damage,
        p["s_c"] + p["k_cn"] * g / (1 + g) - p["mu_c"] * c_a,
    ]


class InflammationModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.immune_lymphatic.inflammation",
        twin=DTKind.IMMUNE_LYMPHATIC, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Course of an acute inflammatory response and its resolution",
        inputs=(Port("pathogen_inoculum", "1", "input:scenario"),
                Port("inoculations", "1", "input:scenario"),
                Port("antimicrobial_kill", "/h", "input:treatment")),
        outputs=(Port("pathogen", "1"), Port("activated_phagocytes", "1"),
                 Port("tissue_damage", "1"), Port("anti_inflammatory", "1"),
                 Port("inflammation_index", "1")),
        explainers=("sensitivity.local", "counterfactual.scenario"))
    params_stem = "inflammation"
    state_names = ("P", "N_star", "D", "C_A")
    time_scale_s = 3600.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {"P": float(inputs.get("pathogen_inoculum", 0.0)), "N_star": 0.0, "D": 0.0,
                "C_A": p["s_c"] / p["mu_c"]}

    def impulses(self, scenario: c.Scenario | None, inputs: Inputs) -> list[Impulse]:
        """Later inoculations from `inoculations` [{t_s, amount}]."""
        return [(float(i["t_s"]) / self.time_scale_s, {"P": float(i["amount"])})
                for i in inputs.get("inoculations", [])]

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        return reynolds_rhs(y, p, float(u.get("antimicrobial_kill", 0.0)))

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        return {"pathogen": float(y[0]), "activated_phagocytes": float(y[1]),
                "tissue_damage": float(y[2]), "anti_inflammatory": float(y[3]),
                "inflammation_index": float(y[1] / (1 + (y[3] / p["c_inf"]) ** 2))}
