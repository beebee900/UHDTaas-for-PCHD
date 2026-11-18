"""The six demo personas as fixed documents (design 06, 6.4.2).

A persona document joins the persona's identity (`atra.personas`), the scenario facts of
`synth/personas/facts.yaml`, findings drawn for its conditions, one note, device readings
and labs from its truth physiology. Everything is seeded by the persona's `hdt_id`, so the
written JSON is byte-identical on every run. The truth itself goes to the truth directory,
not into the document.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from ahdt.models.base import Layer4Base
from atra.personas import PERSONAS, Persona
from synth.conditions import Episode
from synth.params import HERE
from synth.population import Person
from synth.records import device_readings, findings, labs, note
from synth.truth import PersonTruth, person_truth

PERSONA_DIR = HERE / "personas"
FACTS = PERSONA_DIR / "facts.yaml"
START = datetime(2026, 1, 1, tzinfo=UTC)
EPISODE_ONSET = datetime(2026, 9, 28, 8, 0, tzinfo=UTC)


def facts() -> Mapping[str, Any]:
    data: Mapping[str, Any] = yaml.safe_load(FACTS.read_text())
    return data


def _person(p: Persona, conditions: list[str]) -> Person:
    return Person(hdt_id=p.hdt_id, national_id=p.synthetic_national_id, sex=p.sex,
                  age_years=p.age_years, lga="Surulere", household_id=f"hh-persona-{p.key}",
                  sdoh={}, hb_genotype="HbSS" if p.key == "ef" else "HbAA", pgx={},
                  conditions=conditions)


async def build_persona(p: Persona, models: Mapping[str, Layer4Base]
                        ) -> tuple[dict[str, Any], PersonTruth]:
    f = facts()[p.key]
    person = _person(p, list(f.get("conditions", [])))
    eps = ([Episode(f"ep-persona-{p.key}", p.hdt_id, "cond.malaria_falciparum", EPISODE_ONSET,
                    14.0, "severe" if p.key == "bm" else "uncomplicated")]
           if "cond.malaria_falciparum" in person.conditions else [])
    sbp = next((o["value"] for o in f.get("observations", []) if o["field"] == "sbp"), None)
    truth = await person_truth(person, models, eps, target_sbp=sbp)
    found = findings(person, person.conditions, "persona-findings",
                     severity=eps[0].severity if eps else None)
    document = {
        "key": p.key, "hdt_id": p.hdt_id, "initials": p.initials, "sex": p.sex,
        "age_years": p.age_years, "language": p.language, "tenant_id": p.tenant_id,
        "scenario": p.scenario, "facts": f, "findings": found,
        "notes": [note(person, person.conditions[0], found,
                       EPISODE_ONSET + timedelta(hours=1))],
        "observations": device_readings(person, truth, eps, START),
        "labs": labs(person, truth, eps, START),
        "episodes": [e.record() for e in eps],
    }
    return document, truth


def dumps(document: Mapping[str, Any]) -> str:
    return json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n"


async def write_personas(models: Mapping[str, Layer4Base], *, out: Path = PERSONA_DIR,
                         truth_dir: Path | None = None) -> list[Path]:
    paths = []
    for p in PERSONAS:
        document, truth = await build_persona(p, models)
        path = out / f"{p.key}.json"
        _save(path, dumps(document))
        paths.append(path)
        if truth_dir is not None:
            _save(truth_dir / f"persona-{p.key}.json",
                  json.dumps(truth.record(), indent=1, sort_keys=True) + "\n")
    return paths


def _save(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def load(key: str) -> dict[str, Any]:
    document: dict[str, Any] = json.loads((PERSONA_DIR / f"{key}.json").read_text())
    return document
