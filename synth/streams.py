"""Truth streams for the device simulators (design 04, 4.1.1; design 06, 6.4.1).

A persona's stream covers `hours` from its malaria episode onset (else the persona start)
with one sample per field per `step_s`. Vital signs come from the persona's truth physiology;
temperature follows the fever of a malaria episode while the parasitaemia is above the RDT
detection limit, as `synth.records` reads it. Fields without a truth-mode model use the
`device_streams` assumptions of `synth/sources.yaml`, drawn once per person from its seed.
Lab panels, genotypes and questionnaire answers go in the stream's documents.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from datetime import timedelta
from typing import Any

import numpy as np

from ahdt.models.base import Layer4Base
from ahdt.models.modes import person_seed
from atra.config import ROOT
from atra.personas import BY_KEY
from edge.devices.sim.base import TruthStream
from synth.params import sources
from synth.personas import EPISODE_ONSET, START, build_persona
from synth.truth import CLINIC_AIR, PersonTruth

HOUR_S = 3600.0
RESPIRATORY = ("cond.asthma", "cond.copd", "cond.tuberculosis", "cond.pneumonia")
LABS = (("14682-9", "Creatinine", "creatinine", "umol/L", 1),
        ("718-7", "Hemoglobin", "hb", "g/dL", 1))


def _flat(value: float, times: Iterable[float]) -> list[tuple[float, float]]:
    return [(float(t), float(value)) for t in times]


def _answers(rng: np.random.Generator, name: str, weights: list[float]) -> dict[str, str]:
    q = kb_questionnaire(name)
    p = np.asarray(weights) / sum(weights)
    return {i["linkId"]: str(rng.choice(4, p=p)) for i in q["item"][0]["item"]}


def kb_questionnaire(name: str) -> Mapping[str, Any]:
    data: Mapping[str, Any] = json.loads(
        (ROOT / "kb" / "questionnaires" / f"{name}.json").read_text())
    return data


def stream_from_truth(doc: Mapping[str, Any], truth: PersonTruth, *, hours: float = 24.0,
                      step_s: float = HOUR_S) -> TruthStream:
    cfg = sources()["device_streams"]
    rdt = float(sources()["labs"]["rdt_detection_parasitaemia_percent"])
    rng = np.random.default_rng(person_seed(truth.hdt_id, "device_streams"))
    sex = doc["sex"]
    conditions = list(doc["facts"].get("conditions", []))
    episodes = doc.get("episodes", [])
    start = EPISODE_ONSET if episodes else START
    times = np.arange(0.0, hours * HOUR_S + 1e-9, step_s)
    b = truth.baseline
    series: dict[str, list[tuple[float, float]]] = {
        name: _flat(b[key], times) for name, key in (
            ("heart_rate", "heart_rate"), ("sbp", "sbp"), ("dbp", "dbp"), ("spo2", "spo2"))}
    if "glucose" in b:
        series["glucose"] = _flat(b["glucose"], times)
    temps = []
    for t in times:
        fever = False
        for ep in truth.episodes.values():
            day = t / 86400.0
            i = int(np.argmin(np.abs(np.asarray(ep["t_d"]) - day)))
            fever = fever or ep["parasitaemia"][i] >= rdt
        temps.append((float(t), truth.fever_temp if fever else b["temperature"]))
    series["temperature"] = temps
    fixed = {o["field"]: o["value"] for o in doc["facts"].get("observations", [])}

    def draw(key: str, mean: float | None = None) -> float:
        spec = cfg[key]
        centre = mean if mean is not None else spec.get(sex, spec.get("mean"))
        return float(max(0.0, rng.normal(centre, spec["sd"])))

    weight = float(fixed.get("weight", draw("weight_kg")))
    for name, value in (("weight", weight), ("height", draw("height_cm")),
                        ("pef", draw("pef_l_min")), ("fev1", draw("fev1_l")),
                        ("hrv_rmssd", draw("hrv_rmssd_ms")), ("cadence", draw("cadence_per_min")),
                        ("pm25", draw("pm25_ugm3")),
                        ("ambient_temp", CLINIC_AIR["air_temperature"]),
                        ("humidity", CLINIC_AIR["relative_humidity"])):
        series[name] = _flat(value, times)
    series["active_minutes"] = _flat(min(60.0, draw("active_minutes_per_h")), times)
    cough = cfg["cough_events_per_h"]
    series["cough_events"] = _flat(
        cough["respiratory" if set(conditions) & set(RESPIRATORY) else "healthy"], times)
    days = times[:: max(1, int(86400 // step_s))]
    series["screen_time"] = _flat(draw("screen_time_min_per_d"), days)
    insulin = cfg["insulin"]
    series["insulin_delivered"] = [
        (float(t), insulin["basal_u_per_h"] * step_s / HOUR_S
         + (insulin["meal_bolus_u"] if (start + timedelta(seconds=float(t))).hour
            in insulin["meal_hours"] else 0.0)) for t in times]
    labs = [{"name": "24323-8^Comprehensive metabolic panel^LN", "time_s": 0.0, "results": [
        {"loinc": loinc, "text": text, "value": round(b[key], digits), "unit": unit,
         "digits": digits} for loinc, text, key, unit, digits in LABS]}]
    hb_genotype = "HbSS" if doc["key"] == "ef" else "HbAA"
    weights = list(cfg["questionnaire_answer_weights"])
    documents = {
        "labs": labs,
        "genotypes": {"HBB": {"HbAA": 0, "HbAS": 1, "HbSS": 2}[hb_genotype], "CYP2C19": 0},
        "questionnaires": {name: _answers(rng, name, weights) for name in ("phq9", "gad7")},
    }
    return TruthStream(truth.hdt_id, start, series, documents)


async def persona_stream(key: str, models: Mapping[str, Layer4Base], **kw: Any) -> TruthStream:
    doc, truth = await build_persona(BY_KEY[key], models)
    return stream_from_truth(doc, truth, **kw)

