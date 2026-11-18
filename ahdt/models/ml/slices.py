"""Fairness slice attributes of a synthetic person (design 07, 7.5; `slices.yaml`).

Sex, age band and region come from the WP02 person. Facility level and preferred language
are not in the WP02 records, so each person draws them once from the `slices.yaml` shares
with a seed derived from the person id.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml

from ahdt.models.ml.common import age_band

CONFIG = Path(__file__).with_name("slices.yaml")


@lru_cache(maxsize=1)
def config() -> Mapping[str, Any]:
    data: Mapping[str, Any] = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    return data


def bands() -> list[tuple[str, float, float]]:
    return [(str(b[0]), float(b[1]), float(b[2])) for b in config()["age_bands"]]


def _draw(hdt_id: str, key: str, shares: Mapping[str, float]) -> str:
    seed = int.from_bytes(hashlib.sha256(f"{hdt_id}|slice|{key}".encode()).digest()[:8], "big")
    names = list(shares)
    p = np.asarray([shares[n] for n in names], dtype=float)
    return names[int(np.random.default_rng(seed).choice(len(names), p=p / p.sum()))]


def region_of(lga: str) -> str:
    for group, members in config()["region"]["groups"].items():
        if lga in members:
            return str(group)
    return "other"


def person_slices(person: Mapping[str, Any]) -> dict[str, str]:
    cfg = config()
    hdt_id = str(person["hdt_id"])
    return {"sex": str(person["sex"]),
            "age_band": age_band(float(person["age_years"]), bands()),
            "region": region_of(str(person["lga"])),
            "facility_level": _draw(hdt_id, "facility_level", cfg["facility_level"]["shares"]),
            "language": _draw(hdt_id, "language", cfg["language"]["shares"])}


def slice_columns(persons: Sequence[Mapping[str, Any]]) -> dict[str, list[str]]:
    rows = [person_slices(p) for p in persons]
    return {k: [r[k] for r in rows] for k in rows[0]} if rows else {}
