"""What the services see: device readings, labs, findings and notes (design 06, 6.4.1).

Each generator reads the truth and adds measurement error, so nothing here is truth.
Observations use the JSON shape of the `ingest.<twin>` topics (`raw_from_payload`), so a
build can be replayed through the AHDT ingestion pipeline. Notes are written from a fixed
template and marked synthetic; the LLM writer of the cognitive services replaces it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any

import numpy as np

from ahdt.ingest.fields import field_index
from ahdt.models.modes import person_seed
from synth.conditions import Episode
from synth.params import kb, sources
from synth.population import Person
from synth.truth import PersonTruth


def _quantise(value: float, step: float) -> float:
    return round(round(value / step) * step, 6)


def _obs(hdt_id: str, field: str, value: Any, when: datetime, *, source: str,
         device_id: str | None, key: str) -> dict[str, Any]:
    ref = field_index().by_name(field)
    if ref is None:
        raise KeyError(field)
    return {"record_id": key, "hdt_id": hdt_id,
            "code": {"system": ref.code.system, "code": ref.code.code},
            "value": value, "unit": ref.field.ucum, "effective_time": when.isoformat(),
            "source": source, "device_id": device_id, "idempotency_key": key}


def device_readings(person: Person, truth: PersonTruth, episodes: Sequence[Episode],
                    start: datetime) -> list[dict[str, Any]]:
    """Weekly blood pressure for hypertension, three glucose readings a week for diabetes,
    and twice-daily temperature during a malaria episode."""
    devices = sources()["devices"]
    rng = np.random.default_rng(person_seed(person.hdt_id, "devices"))
    out: list[dict[str, Any]] = []

    def emit(device: str, field: str, true_value: float, when: datetime) -> None:
        spec = devices[device]
        if rng.random() < spec["dropout"]:
            return
        value = _quantise(true_value + rng.normal(0, spec["sd"]), spec["step"])
        out.append(_obs(person.hdt_id, field, value, when, source="device",
                        device_id=f"{device}-{person.hdt_id[-6:]}",
                        key=f"dev-{person.hdt_id}-{field}-{len(out)}"))

    if "cond.hypertension" in person.conditions:
        for week in range(52):
            when = start + timedelta(weeks=week, hours=7)
            emit("bp_cuff", "sbp", truth.baseline["sbp"], when)
            emit("bp_cuff", "dbp", truth.baseline["dbp"], when)
    if "glucose" in truth.baseline:
        for day in range(0, 365, 2):
            emit("glucometer", "glucose", truth.baseline["glucose"],
                 start + timedelta(days=day, hours=9))
    rdt = float(sources()["labs"]["rdt_detection_parasitaemia_percent"])
    for ep in episodes:
        series = truth.episodes[ep.episode_key]
        for t_d, para in zip(series["t_d"], series["parasitaemia"], strict=True):
            if t_d < 0 or (t_d * 2) % 1:
                continue
            temp = truth.fever_temp if para >= rdt else truth.baseline["temperature"]
            emit("thermometer", "temperature", temp, ep.onset + timedelta(days=t_d))
    return out


def labs(person: Person, truth: PersonTruth, episodes: Sequence[Episode],
         start: datetime) -> list[dict[str, Any]]:
    """An annual creatinine and haemoglobin; at each malaria episode an RDT and a
    haemoglobin."""
    cfg = sources()["labs"]
    rng = np.random.default_rng(person_seed(person.hdt_id, "labs"))
    out: list[dict[str, Any]] = []

    def lab(field: str, true_value: float, when: datetime) -> None:
        value = round(true_value * float(1 + rng.normal(0, cfg["assay_cv"][field])), 2)
        out.append(_obs(person.hdt_id, field, value, when, source="manual", device_id=None,
                        key=f"lab-{person.hdt_id}-{field}-{len(out)}"))

    lab("creatinine", truth.baseline["creatinine"], start + timedelta(days=30))
    lab("hb", truth.baseline["hb"], start + timedelta(days=30))
    for ep in episodes:
        para = truth.episodes[ep.episode_key]["parasitaemia"][0]
        out.append({"record_id": f"lab-{person.hdt_id}-rdt-{len(out)}",
                    "hdt_id": person.hdt_id,
                    "code": {"system": "http://loinc.org",
                             "code": str(kb().entry("test.malaria_rdt_hrp2").content()["loinc"])},
                    "value": bool(para >= cfg["rdt_detection_parasitaemia_percent"]),
                    "unit": "1", "effective_time": ep.onset.isoformat(), "source": "manual",
                    "result_of": "malaria_rdt"})
        lab("hb", truth.baseline["hb"], ep.onset)
    return out


def findings(person: Person, conditions: Sequence[str], seed_key: str,
             severity: str | None = None) -> list[str]:
    """Findings sampled from `kb/associations.yaml` with `assoc.strength_probability`."""
    probs: Mapping[str, float] = kb().entry("assoc.strength_probability").content()["value"]
    rng = np.random.default_rng(person_seed(person.hdt_id, seed_key))
    found: list[str] = []
    for eid in kb().ids():
        if not eid.startswith("assoc.") or eid == "assoc.strength_probability":
            continue
        a = kb().entry(eid).content()
        if a.get("condition") not in conditions or a.get("severity") not in (None, severity):
            continue
        for f in a["findings"]:
            if f["finding"] not in found and rng.random() < probs[f["strength"]]:
                found.append(f["finding"])
    return found


def note(person: Person, condition: str, found: Sequence[str], when: datetime
         ) -> dict[str, Any]:
    names = [str(kb().entry(f).content()["name"]).lower() for f in found]
    cond = str(kb().entry(condition).content()["name"])
    text = (f"History of Present Illness: {person.age_years}-year-old {person.sex} presenting "
            f"with {', '.join(names) or 'no specific complaints'}.\n"
            f"Assessment: {cond}.\nPlan: treat per guideline and review in 48 hours.")
    return {"hdt_id": person.hdt_id, "type": "note", "date": when.isoformat(), "text": text,
            "synthetic": True, "writer": "template"}
