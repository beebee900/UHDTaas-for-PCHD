"""Observational treatment cohort and logged therapy trajectories (design 06, 6.4.1).

The cohort tests causal estimators: treatment depends on confounders (age, severity,
distance to the facility), and the outcome comes from a structural model whose
heterogeneous effect is known, so an estimate can be compared with the truth. The
trajectories are offline RL data: monthly antihypertensive titration by a guideline-like
behaviour policy with noise, with systolic pressure from the heart model.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pyarrow as pa

from ahdt.models.base import Layer4Base
from synth.params import sources
from synth.truth import HEART, RF_STEP, heart_state


def treatment_cohort(seed: int) -> tuple[pa.Table, pa.Table]:
    """(observed table, truth table with the individual effect)."""
    cfg = sources()["treatment_cohort"]
    eff = cfg["true_effect"]
    rng = np.random.default_rng(seed + 11)
    n = int(cfg["persons"])
    age = rng.integers(25, 80, n)
    severe = rng.random(n) < 0.3
    distance_km = rng.gamma(2.0, 3.0, n)
    logit = -0.5 + 0.03 * (age - 50) + 1.2 * severe - 0.15 * distance_km
    treated = rng.random(n) < 1 / (1 + np.exp(-logit))
    baseline = 150 + 0.4 * (age - 50) + 8 * severe + rng.normal(0, 6, n)
    tau = eff["intercept"] + eff["per_decade_age"] * (age - 50) / 10 + eff["severe"] * severe
    outcome = baseline + treated * tau + rng.normal(0, 5, n)
    ids = [f"coh-{seed}-{i:05d}" for i in range(n)]
    observed = pa.table({"id": ids, "age": age, "severe": severe, "distance_km": distance_km,
                         "treated": treated, "sbp_followup": outcome})
    truth = pa.table({"id": ids, "tau": tau, "propensity": 1 / (1 + np.exp(-logit))})
    return observed, truth


async def therapy_trajectories(models: Mapping[str, Layer4Base], seed: int, persons: int = 50
                               ) -> pa.Table:
    cfg = sources()["therapy_trajectories"]
    bp = sources()["blood_pressure"]["resistance_factor_hypertension"]
    rng = np.random.default_rng(seed + 12)
    rows: dict[str, list[Any]] = {k: [] for k in
                                  ("episode", "visit", "sbp", "dose_step", "action", "next_sbp")}
    for e in range(persons):
        rf0 = float(rng.normal(bp["mean"], bp["sd"]))
        dose = 0
        sbp = await _sbp(models, rf0, dose,
                         cfg["dose_effect_on_resistance"])
        for visit in range(int(cfg["visits"])):
            guideline = 1 if sbp >= 140 else (-1 if sbp < 110 and dose > 0 else 0)
            action = guideline if rng.random() > cfg["behaviour_noise"] else int(
                rng.integers(-1, 2))
            dose = int(min(max(dose + action, 0), 4))
            nxt = await _sbp(models, rf0, dose,
                             cfg["dose_effect_on_resistance"])
            for k, v in (("episode", e), ("visit", visit), ("sbp", sbp), ("dose_step", dose),
                         ("action", action), ("next_sbp", nxt)):
                rows[k].append(v)
            sbp = nxt
    return pa.table(rows)


async def _sbp(models: Mapping[str, Layer4Base], rf0: float, dose: int,
               effect: float) -> float:
    rf = round(max(0.7, rf0 - effect * dose) / RF_STEP) * RF_STEP
    return round((await heart_state(models[HEART], rf))["sbp"], 1)
