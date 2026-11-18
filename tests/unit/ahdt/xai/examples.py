"""One runnable subject per registered model, built from small hand-made inputs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd

from ahdt.models.catalogue import default_catalogue
from ahdt.models.ml.artifacts import LAPTOP_ROOT
from ahdt.models.reference import ReferenceStateModel
from ahdt.xai import subjects as S
from ahdt.xai.probes import mechanistic_subject, reference_subject, rule_subject
from ahdt.xai.registry import T1_KINDS
from ahdt.xai.types import Subject
from atra import contracts as c

ROOT = LAPTOP_ROOT
RNG = np.random.default_rng(5)

ROWS: dict[str, dict[str, float]] = {
    "ahdt.respiratory.exacerbation_risk": {
        "pef_pct_best": 70, "symptom_score": 3, "night_waking": 1, "reliever_puffs": 4,
        "pm25": 40, "viral_illness": 1, "adherence": 0.6, "prior_exacerbations": 1,
        "age_years": 35},
    "ahdt.respiratory.spo2_desaturation_detection": {
        "spo2.mean": 93, "spo2.min": 90, "spo2.max": 97, "spo2.n": 30, "heart_rate.mean": 88,
        "heart_rate.max": 110},
    "ahdt.musculoskeletal.gait_and_fall_risk": {
        "gait_speed.mean": 0.8, "cadence.mean": 95, "stride_time_cv.mean": 5},
    "ahdt.haematological.anaemia_and_sickle_cell_crisis_risk": {
        "hb": 8.5, "hbf": 6, "infection": 1, "dehydration": 0, "temperature": 38,
        "hydroxyurea": 0, "age_years": 20},
    "ahdt.whole_body.deterioration_risk": {
        "news2": 5, "age_years": 60, "respiration_rate": 22, "spo2": 93, "systolic_bp": 105,
        "pulse": 108, "temperature": 38, "d6.respiration_rate": 20, "d6.spo2": 95,
        "d6.systolic_bp": 115, "d6.pulse": 95, "d6.temperature": 37.2},
    "ahdt.behavioural_cognitive.affect_and_stress": {
        "hr_mean": 82, "hrv_rmssd": 30, "hrv_sdnn": 45, "hrv_pnn50": 10, "eda_mean": 3,
        "eda_std": 0.5, "eda_slope": 0.01, "scr_count": 4, "skin_temp": 33,
        "skin_temp_slope": 0.0},
    "ahdt.behavioural_cognitive.adherence": {
        "age_years": 40, "pills_per_day": 3, "distance_km": 8, "low_income": 1, "insured": 0,
        "depression": 1},
}


def _series(n: int, centre: list[float], sd: list[float]) -> np.ndarray:
    return np.column_stack([RNG.normal(m, s, n) for m, s in zip(centre, sd, strict=True)])


def subject_for_t1(model_id: str, root: Path = ROOT) -> Subject:
    d = root / model_id
    kind = T1_KINDS[model_id]
    if kind == "tabular":
        return S.tabular_subject(model_id, d, ROWS[model_id])
    if model_id.endswith("blood_pressure_forecasting"):
        return S.window_subject(model_id, d, _series(56, [130, 82], [8, 5]))
    if model_id.endswith("glucose_forecasting"):
        return S.window_subject(model_id, d, _series(56, [6.0], [1.0]))
    if model_id.endswith("news2_component_forecasting"):
        return S.window_subject(model_id, d, _series(24, [20, 94, 112, 95, 37.5],
                                                     [2, 2, 8, 8, 0.4]), target="spo2")
    if model_id.endswith("clinical_health_state"):
        obs = np.array([[0, 0, 0], [0, 1, 1], [1, 1, 1], [1, 1, 2], [2, 2, 3]])
        return S.sequence_subject(model_id, d, obs, "critical")
    if model_id.endswith("mental_health_trajectory"):
        obs = np.array([[6, 5], [8, 6], [11, 9], [14, 11], [16, 12]], dtype=float)
        return S.sequence_subject(model_id, d, obs, "moderate")
    if model_id.endswith("lifestyle"):
        hist = [dict(steps=float(s), active_minutes=float(a), sleep_duration=float(h),
                     screen_time=float(t)) for s, a, h, t in zip(
            RNG.normal(6000, 800, 20), RNG.normal(40, 8, 20), RNG.normal(7, 0.5, 20),
            RNG.normal(180, 30, 20), strict=True)]
        return S.online_subject(model_id, d, hist, dict(steps=1500.0, active_minutes=5.0,
                                                        sleep_duration=4.0, screen_time=420.0))
    if model_id.endswith("arrhythmia_detection"):
        t = np.arange(2500) / 250
        ecg = np.sin(2 * np.pi * 1.2 * t) + 0.3 * np.sin(2 * np.pi * 7 * t) \
            + RNG.normal(0, 0.05, t.size)
        return S.signal_subject(model_id, d, ecg)
    if model_id.endswith("arrhythmia_beat_classification"):
        beat = np.exp(-((np.arange(256) - 96) / 10.0) ** 2) + RNG.normal(0, 0.02, 256)
        return S.beat_subject(model_id, d, beat, np.array([0.8, 0.8, 1.0, 1.0, 1.0]))
    if model_id.endswith("eeg_analysis_and_sleep_staging"):
        t = np.arange(3000) / 100
        return S.signal_subject(model_id, d, np.sin(2 * np.pi * 10 * t) + RNG.normal(0, 0.3, 3000))
    if model_id.endswith("social_network"):
        g = nx.path_graph([f"hdt-{i:012x}" for i in range(8)])
        nodes = pd.DataFrame({"hdt_id": list(g.nodes), "age_years": RNG.uniform(5, 70, 8),
                              "female": RNG.integers(0, 2, 8), "low_income": RNG.integers(0, 2, 8),
                              "insured": RNG.integers(0, 2, 8),
                              "tertiary_education": RNG.integers(0, 2, 8),
                              "chronic": RNG.integers(0, 2, 8)})
        return S.graph_subject(model_id, d, nodes, g, "hdt-000000000003")
    raise KeyError(model_id)


def subject_for_catalogue(model_id: str) -> Subject:
    model = default_catalogue()[model_id]
    if isinstance(model, ReferenceStateModel):
        return reference_subject(model)
    if model.spec.family is c.ModelFamily.SEMANTIC:
        return rule_subject(model)
    return mechanistic_subject(model)


def subject_for(model_id: str) -> Any:
    return subject_for_t1(model_id) if model_id in T1_KINDS else subject_for_catalogue(model_id)
