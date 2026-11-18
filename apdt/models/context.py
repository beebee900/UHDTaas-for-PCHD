"""The inputs the Layer 4 models share: the patient and what has been observed."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

import yaml

from ahdt.models.reference import default_kb
from atra.kb import KnowledgeBase

HERE = Path(__file__).resolve().parent

type Pregnancy = Literal["none", "t1", "t2", "t3"]


def kb() -> KnowledgeBase:
    """The shared knowledge base; loading it takes seconds, so every model uses this one."""
    return default_kb()


@lru_cache(maxsize=1)
def params() -> Mapping[str, Any]:
    """Parameters that the kb does not hold. Each entry is an assumption with its reason."""
    data: Mapping[str, Any] = yaml.safe_load((HERE / "params.yaml").read_text(encoding="utf-8"))
    return data


def param(name: str) -> Any:
    return params()[name]["value"]


@dataclass(frozen=True)
class Patient:
    """Who is being assessed. `medications` are generic names; `flags` are kb-style tokens
    (for example `cardiovascular_disease`) that interaction rules can name."""

    age_years: float
    sex: Literal["female", "male"]
    weight_kg: float | None = None
    pregnancy: Pregnancy = "none"
    hb_genotype: str | None = None
    oral_intake: bool = True
    intramuscular_available: bool = True
    referral_possible: bool = True
    egfr: float | None = None
    conditions: tuple[str, ...] = ()
    medications: tuple[str, ...] = ()
    allergies: tuple[str, ...] = ()
    flags: frozenset[str] = frozenset()
    pgx: Mapping[str, str] = field(default_factory=dict)
    context: Mapping[str, Any] = field(default_factory=dict)
    region: str = "lagos"
    season: Literal["dry", "rainy"] = "rainy"
    tenant_id: str = "fac-a"

    @property
    def patient_group(self) -> str:
        grp = kb().entry("dosing.patient_group").content()
        if self.weight_kg is not None and self.weight_kg > float(grp["adult_dosing_above_kg"]):
            return "adult"
        return "child" if self.age_years < float(grp["child_age_below_years"]) else "adult"


@dataclass
class Observations:
    """Findings, test results and measurements. `findings` maps a kb finding id to present
    (True) or absent (False); an id not listed is unknown. `tests` maps a kb test id to
    positive (True) or negative (False). `measurements` maps a field name to its value."""

    findings: dict[str, bool] = field(default_factory=dict)
    tests: dict[str, bool] = field(default_factory=dict)
    measurements: dict[str, float] = field(default_factory=dict)
    avpu: str = "A"
