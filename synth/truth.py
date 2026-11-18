"""Ground-truth physiology from the AHDT models in truth mode (design 06, 6.4.1).

Only `evaluation/` and the generators in `synth/` read this module's output; the services
under `ahdt/` and `apdt/` never do (the isolation test enforces it).

Per person: the heart model with a person-specific systemic resistance factor (blood
pressure, heart rate), gas exchange (SpO2), thermoregulation (core temperature, and the
same with a malaria fever), the kidney (creatinine), red cells (haemoglobin) and, for type 2
diabetes, the glucose model under glycaemic deterioration (glucose two hours after a meal).
Per malaria episode: the infection model from inoculation, reported from symptom onset
(the end of the pre-patent period) and treated as `synth/sources.yaml` sets.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np

from ahdt.models import drivers
from ahdt.models.base import Layer4Base
from ahdt.models.modes import person_seed, run_truth
from synth.conditions import Episode
from synth.params import sources
from synth.population import Person

HEART = "ahdt.cardiovascular.heart_chambers_and_valves"
LUNGS = "ahdt.respiratory.lungs_and_gas_exchange"
THERMO = "ahdt.integumentary.thermoregulation"
KIDNEY = "ahdt.renal_urinary.kidney_and_renal_function"
ERYTHRO = "ahdt.haematological.bone_marrow_and_erythrocytes"
GLUCOSE = "ahdt.endocrine.glucose_insulin_and_metabolic_regulation"
INFECTION = "ahdt.immune_lymphatic.infection_response"
DAY_S = 86400.0
FEVER_K = 1.5
CLINIC_AIR = {"air_temperature": 28.0, "relative_humidity": 70.0}


@dataclass
class PersonTruth:
    hdt_id: str
    resistance_factor: float
    baseline: dict[str, float]
    fever_temp: float
    episodes: dict[str, dict[str, list[float]]] = field(default_factory=dict)

    def record(self) -> dict[str, Any]:
        return asdict(self)


RF_STEP = 0.005
_HEART: dict[float, dict[str, float]] = {}


async def heart_state(model: Layer4Base, rf: float) -> dict[str, float]:
    """Blood pressure and heart rate at a resistance factor. The heart runs with published
    parameters, so the result depends on the factor alone and is computed once per value."""
    key = round(rf, 6)
    if key not in _HEART:
        run = await run_truth(model, hdt_id="hdt-000000000000", horizon_s=20, step_s=10,
                              vary=False, inputs={"resistance_factor": key})
        _HEART[key] = {"sbp": _last(run, "sbp"), "dbp": _last(run, "dbp"),
                       "heart_rate": _last(run, "heart_rate")}
    return dict(_HEART[key])


def _last(run: Any, name: str) -> float:
    return float(run.trajectory.series[name][-1])


async def resistance_for(model: Layer4Base, sbp: float) -> float:
    """The resistance factor at which the heart model gives the systolic pressure `sbp`."""
    lo, hi = 0.7, 3.0
    while hi - lo > RF_STEP:
        mid = round((lo + hi) / 2 / RF_STEP) * RF_STEP
        if mid in (lo, hi):
            break
        if (await heart_state(model, mid))["sbp"] < sbp:
            lo = mid
        else:
            hi = mid
    return lo


async def person_truth(person: Person, models: Mapping[str, Layer4Base],
                       episodes: Sequence[Episode], *, target_sbp: float | None = None
                       ) -> PersonTruth:
    """`target_sbp` fixes the systolic pressure (personas); otherwise the resistance factor
    is drawn from the person's hypertension status."""
    h = person.hdt_id
    if target_sbp is not None:
        rf = await resistance_for(models[HEART], target_sbp)
    else:
        bp = sources()["blood_pressure"]
        rng = np.random.default_rng(person_seed(person.hdt_id, HEART))
        cfg = bp["resistance_factor_hypertension" if "cond.hypertension" in person.conditions
                 else "resistance_factor_normal"]
        rf = float(max(0.7, rng.normal(cfg["mean"], cfg["sd"])))
        rf = round(rf / RF_STEP) * RF_STEP
    pressures = await heart_state(models[HEART], rf)
    lungs = await run_truth(models[LUNGS], hdt_id=h, horizon_s=600, step_s=300)
    thermo = await run_truth(models[THERMO], hdt_id=h, horizon_s=4 * 3600, step_s=3600,
                             inputs=CLINIC_AIR)
    fever = await run_truth(models[THERMO], hdt_id=h, horizon_s=4 * 3600, step_s=3600,
                            inputs={**CLINIC_AIR, "fever": FEVER_K})
    kidney = await run_truth(models[KIDNEY], hdt_id=h, horizon_s=DAY_S, step_s=DAY_S)
    erythro = await run_truth(models[ERYTHRO], hdt_id=h, horizon_s=DAY_S, step_s=DAY_S)
    baseline = {**pressures, "spo2": _last(lungs, "spo2"),
                "temperature": _last(thermo, "core_temp"),
                "creatinine": _last(kidney, "creatinine"), "hb": _last(erythro, "hb")}
    if "cond.diabetes_type2" in person.conditions:
        cfg = sources()["glucose"]
        worse = drivers.glycaemic_deterioration(0, cfg["sensitivity_decline_per_year"])
        meal = {"meals": [{"t_s": 0, "carbs_g": cfg["meal_carbs_g"]}]}
        glucose = await run_truth(models[GLUCOSE], hdt_id=h, horizon_s=2 * 3600, step_s=1800,
                                  inputs=meal, drivers=[worse])
        baseline["glucose"] = _last(glucose, "glucose")
    truth = PersonTruth(h, rf, baseline, _last(fever, "core_temp"))
    mal = sources()["malaria_episodes"]
    pre = float(mal["prepatent_d"])
    for ep in episodes:
        infection = drivers.malaria(0, mal["merozoite_release"],
                                    treatment_after_d=pre + mal["treatment_after_onset_d"],
                                    antimalarial_kill=mal["antimalarial_kill"])
        run = await run_truth(models[INFECTION], hdt_id=h,
                              horizon_s=(pre + ep.duration_d) * DAY_S, step_s=DAY_S / 4,
                              drivers=[infection], salt=hash_key(ep))
        keep = [i for i, t in enumerate(run.trajectory.t) if t >= pre * DAY_S]
        truth.episodes[ep.episode_key] = {
            "t_d": [run.trajectory.t[i] / DAY_S - pre for i in keep],
            "parasitaemia": [run.trajectory.series["parasitaemia"][i] for i in keep]}
    return truth


def hash_key(ep: Episode) -> int:
    return int(ep.onset.timestamp()) % 1_000_003
