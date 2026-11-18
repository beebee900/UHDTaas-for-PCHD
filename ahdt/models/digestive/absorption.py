"""Stomach and intestine absorption (inventory item 5, digestive absorption).

Glucose appearance follows the gastric emptying and absorption subsystem of Dalla Man et
al. (2007). Oral drugs are absorbed first-order with the rate constant `ka` of the drug,
which the PBPK model reads from the absorption facet.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Impulse, Inputs, ModelSpec, OdeModel, Params, Port
from ahdt.models.digestive.gut import GUT_STATES, gut_rates, last_dose, meals
from atra import contracts as c
from atra.connectors import DTKind


class AbsorptionModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.digestive.stomach_and_intestine_absorption",
        twin=DTKind.DIGESTIVE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Rate of appearance of meal glucose and oral drug absorption",
        instances=("UBERON:0000945", "UBERON:0000160"),
        inputs=(Port("meals", "g", "input:scenario"), Port("ka", "/h", "input:drug")),
        outputs=(Port("absorption_rate", "mg/kg/min"), Port("gastric_emptying_rate", "/min"),
                 Port("transit_time", "min"), Port("stomach_content", "mg"),
                 Port("drug_absorption_rate", "mg/h")),
        explainers=("sensitivity.local",))
    params_stem = "absorption"
    state_names = (*GUT_STATES, "A_drug")
    time_scale_s = 60.0
    max_step = 5.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return dict.fromkeys(self.state_names, 0.0)

    def drive(self, scenario: c.Scenario | None, inputs: Inputs) -> Any:
        schedule = meals(scenario, inputs, self.time_scale_s)
        ka = inputs.get("ka")
        return lambda t: {"dose": last_dose(t, schedule), "ka": ka}

    def impulses(self, scenario: c.Scenario | None, inputs: Inputs) -> list[Impulse]:
        kicks: list[Impulse] = [(t, {"Q_sto1": mg})
                                for t, mg in meals(scenario, inputs, self.time_scale_s)]
        if scenario is not None and scenario.drug is not None and scenario.drug.route == "oral":
            kicks += [(h * 60.0, {"A_drug": scenario.drug.dose_mg})
                      for h in scenario.drug.schedule_h]
        return kicks

    def _ka_per_min(self, u: Mapping[str, Any]) -> float:
        ka = u.get("ka")
        return float(ka) / 60.0 if ka is not None else 0.0

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        q1, q2, qg, a_drug = y
        d1, d2, dg, _, _ = gut_rates(q1, q2, qg, float(u.get("dose", 0.0)), p)
        return [d1, d2, dg, -self._ka_per_min(u) * a_drug]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        q1, q2, qg, a_drug = y
        _, _, _, ra, k_empt = gut_rates(q1, q2, qg, float(u.get("dose", 0.0)), p)
        return {"absorption_rate": ra, "gastric_emptying_rate": k_empt,
                "transit_time": 1.0 / p["k_abs"], "stomach_content": q1 + q2,
                "drug_absorption_rate": self._ka_per_min(u) * a_drug * 60.0}
