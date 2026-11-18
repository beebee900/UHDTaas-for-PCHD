"""Chronic conditions and acute episodes over one simulated year (design 06, 6.4.1).

Chronic conditions use the sourced priors of `kb/priors.yaml` within each prior's own
population, combined by `prior.combination` (one-way breakdowns scaled independently).
Conditions without a sourced prior are not sampled here; the personas carry them.
Malaria episodes are a monthly Poisson process for children under five (the surveyed
group): incidence = prevalence / mean duration, with the dry-season factor of
`synth/sources.yaml`.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np

from synth.params import prior, sources
from synth.population import Person

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


@dataclass
class Episode:
    episode_key: str
    hdt_id: str
    condition: str
    onset: datetime
    duration_d: float
    severity: str

    def record(self) -> dict[str, Any]:
        out = asdict(self)
        out["onset"] = self.onset.isoformat()
        return out


def _scaled(base: float, factors: Sequence[float | None]) -> float:
    p = base
    for f in factors:
        if f is not None:
            p *= f / base
    return min(p, 100.0) / 100.0


def _htn_age_band(age: int) -> str | None:
    if age < 18:
        return None
    for hi, band in ((30, "<30"), (40, "30-39"), (50, "40-49"), (60, "50-59"), (70, "60-69")):
        if age < hi:
            return band
    return "70+"


def p_hypertension(person: Person) -> float:
    pr = prior("hypertension")
    band = _htn_age_band(person.age_years)
    if band is None:
        return 0.0
    return _scaled(float(pr["prevalence_pct"]),
                   [pr["by_age_pct"][band], pr["by_sex_pct"][person.sex]])


def p_diabetes(person: Person) -> float:
    return float(prior("diabetes_type2")["prevalence_pct"]) / 100.0 if person.age_years >= 18 \
        else 0.0


def p_hiv(person: Person) -> float:
    return float(prior("hiv")["prevalence_pct"]) / 100.0 if 15 <= person.age_years <= 49 \
        else 0.0


CHRONIC: Mapping[str, Any] = {"cond.hypertension": p_hypertension,
                              "cond.diabetes_type2": p_diabetes, "cond.hiv": p_hiv}


def assign_chronic(persons: Sequence[Person], seed: int) -> None:
    rng = np.random.default_rng(seed + 1)
    for p in persons:
        for cond, fn in CHRONIC.items():
            if rng.random() < fn(p):
                p.conditions.append(cond)


def malaria_rate_per_day(month: str) -> float:
    pr = prior("malaria_falciparum")
    cfg = sources()["malaria_episodes"]
    base = float(pr["prevalence_pct"]) / 100.0 / float(cfg["mean_duration_d"])
    if month in pr.get("by_month_pct", {}):
        base *= float(pr["by_month_pct"][month]) / float(pr["national_pct"])
    return base if month in cfg["rainy_months"] else base * float(cfg["dry_season_factor"])


def episodes(persons: Sequence[Person], seed: int, year: int = 2026) -> list[Episode]:
    rng = np.random.default_rng(seed + 2)
    out: list[Episode] = []
    duration = float(sources()["malaria_episodes"]["mean_duration_d"])
    for p in persons:
        if p.age_years >= 5:
            continue
        for m, month in enumerate(MONTHS):
            start = datetime(year, m + 1, 1, tzinfo=UTC)
            days = ((datetime(year + 1, 1, 1, tzinfo=UTC) if m == 11
                     else datetime(year, m + 2, 1, tzinfo=UTC)) - start).days
            for _ in range(int(rng.poisson(malaria_rate_per_day(month) * days))):
                onset = start + timedelta(days=float(rng.uniform(0, days)))
                out.append(Episode(f"ep-{p.hdt_id}-{len(out)}", p.hdt_id,
                                   "cond.malaria_falciparum", onset, duration, "uncomplicated"))
    return out
