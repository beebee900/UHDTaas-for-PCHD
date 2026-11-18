"""Nutrition and hydration (inventory item 5).

- Resting energy expenditure by the Mifflin-St Jeor equation; total expenditure is the
  resting value times the physical activity level.
- Body weight changes with the energy balance at a fixed energy density of tissue.
- Body water starts at the Watson (1980) estimate and moves with water intake and losses;
  the hydration deficit is the fractional loss from that estimate.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from ahdt.models.reference import person_value
from ahdt.models.renal_urinary.kidney import total_body_water
from atra import contracts as c
from atra.connectors import DTKind


def resting_energy(weight: float, height: float, age: float, female: bool, p: Params) -> float:
    return (p["w_coef"] * weight + p["h_coef"] * height - p["a_coef"] * age
            + (p["female_const"] if female else p["male_const"]))


class NutritionModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.digestive.nutrition_and_hydration",
        twin=DTKind.DIGESTIVE, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Energy balance, weight trajectory and hydration",
        inputs=(Port("weight0", "kg", "field:29463-7"), Port("height", "cm", "field:8302-2"),
                Port("age", "a"), Port("female", "1"), Port("energy_intake", "kcal/d"),
                Port("pal", "1", "input:activity"), Port("water_in", "mL/d"),
                Port("water_out", "mL/d")),
        outputs=(Port("ree", "kcal/d"), Port("energy_balance", "kcal/d"), Port("weight", "kg"),
                 Port("bmi", "kg/m2"), Port("total_body_water", "L"),
                 Port("hydration_deficit", "1")),
        explainers=("counterfactual.scenario",),
        obs_map={"29463-7": "weight"})
    params_stem = "nutrition"
    state_names = ("weight", "tbw")
    time_scale_s = 86400.0

    @staticmethod
    def _person(u: Mapping[str, Any]) -> tuple[float, float, float, bool]:
        return (float(person_value(u, "weight0")), float(person_value(u, "height")),
                float(person_value(u, "age")), bool(person_value(u, "female")))

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        w0, h, age, female = self._person(inputs)
        return {"weight": w0, "tbw": total_body_water(age, h, w0, female)}

    def _balance(self, weight: float, p: Params, u: Mapping[str, Any]) -> tuple[float, float]:
        _, h, age, female = self._person(u)
        ree = resting_energy(weight, h, age, female, p)
        intake = float(u.get("energy_intake", ree * float(u.get("pal", 1.0))))
        return ree, intake - ree * float(u.get("pal", 1.0))

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        _, balance = self._balance(float(y[0]), p, u)
        water = (float(u.get("water_in", 0.0)) - float(u.get("water_out", 0.0))) / 1000.0
        return [balance / p["energy_per_kg"], water]

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        w0, h, age, female = self._person(u)
        ree, balance = self._balance(float(y[0]), p, u)
        tbw0 = total_body_water(age, h, w0, female)
        return {"ree": ree, "energy_balance": balance, "weight": float(y[0]),
                "bmi": float(y[0]) / (h / 100.0) ** 2, "total_body_water": float(y[1]),
                "hydration_deficit": (tbw0 - float(y[1])) / tbw0}
