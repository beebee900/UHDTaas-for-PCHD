"""Gastric emptying and intestinal glucose absorption of Dalla Man et al. (2007).

The subsystem is shared by the Digestive absorption model, which owns the gut instance,
and the Endocrine glucose-insulin model, which uses it when no coupled appearance rate
is supplied.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

from atra import contracts as c

GUT_STATES = ("Q_sto1", "Q_sto2", "Q_gut")


def gastric_emptying_rate(q_sto: float, dose_mg: float, p: Mapping[str, float]) -> float:
    """k_empt (/min) as a function of the stomach content and the last meal's carbohydrate."""
    if dose_mg <= 0:
        return p["k_max"]
    a = 5 / (2 * dose_mg * (1 - p["b"]))
    cc = 5 / (2 * dose_mg * p["d"])
    return p["k_min"] + (p["k_max"] - p["k_min"]) / 2 * (
        math.tanh(a * (q_sto - p["b"] * dose_mg)) - math.tanh(cc * (q_sto - p["d"] * dose_mg))
        + 2)


def gut_rates(q_sto1: float, q_sto2: float, q_gut: float, dose_mg: float,
              p: Mapping[str, float]) -> tuple[float, float, float, float, float]:
    """(dQ_sto1, dQ_sto2, dQ_gut, Ra in mg/kg/min, k_empt in /min)."""
    k_empt = gastric_emptying_rate(q_sto1 + q_sto2, dose_mg, p)
    d1 = -p["k_gri"] * q_sto1
    d2 = -k_empt * q_sto2 + p["k_gri"] * q_sto1
    dg = -p["k_abs"] * q_gut + k_empt * q_sto2
    ra = p["f"] * p["k_abs"] * q_gut / p["BW"]
    return d1, d2, dg, ra, k_empt


def meals(scenario: c.Scenario | None, inputs: Mapping[str, Any],
          time_scale_s: float) -> list[tuple[float, float]]:
    """Meals as (model time, carbohydrate mg) from `diet.meals` [{t_s, carbs_g}]."""
    entries: list[Mapping[str, Any]] = list(inputs.get("meals", []))
    if scenario is not None and scenario.diet:
        entries += list(scenario.diet.get("meals", []))
    return sorted((float(m["t_s"]) / time_scale_s, float(m["carbs_g"]) * 1000.0)
                  for m in entries)


def last_dose(t: float, schedule: list[tuple[float, float]]) -> float:
    dose = 0.0
    for when, mg in schedule:
        if when <= t:
            dose = mg
    return dose
