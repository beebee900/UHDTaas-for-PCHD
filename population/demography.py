"""Cohort-component population projection (design 04, 4.5.3: demographic).

Five-year age groups `0-4` to `75-79` and `80+` by sex, projected in five-year steps:
survivors move up one group (the open group keeps its own survivors), women aged 15 to 49
give births at the age-specific rates, births that survive the step enter `0-4`, and net
migration adds to the working ages. Rates are in `demography.params.yaml`.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ahdt.models.params import ParamSet, load_params

PARAMS = Path(__file__).with_name("demography.params.yaml")
GROUPS = (*(f"{a}-{a + 4}" for a in range(0, 80, 5)), "80+")
STEP_Y = 5.0

type F = NDArray[np.float64]


@lru_cache(maxsize=1)
def params() -> ParamSet:
    return load_params(PARAMS)


def _lower(group: str) -> int:
    return int(group.rstrip("+").split("-")[0])


def _rate_by_group(p: Mapping[str, float]) -> tuple[F, F, F]:
    """(annual mortality, annual fertility of women, annual net migration) per group."""
    mortality, fertility, migration = (np.zeros(len(GROUPS)) for _ in range(3))
    bands = ((0, 5, "mortality_0_4"), (5, 15, "mortality_5_14"), (15, 50, "mortality_15_49"),
             (50, 65, "mortality_50_64"), (65, 80, "mortality_65_79"),
             (80, 200, "mortality_80_plus"))
    for i, g in enumerate(GROUPS):
        lo = _lower(g)
        mortality[i] = next(p[name] for a, b, name in bands if a <= lo < b)
        fertility[i] = p.get(f"asfr_{lo}_{lo + 4}", 0.0)
        migration[i] = p["net_migration_15_34"] if 15 <= lo < 35 else 0.0
    return mortality, fertility, migration


def project(base: Mapping[str, Mapping[str, float]], steps: int = 4,
            paramset: ParamSet | None = None) -> list[dict[str, Any]]:
    """Population by group and sex at the base and after each five-year step.

    `base` is `{group: {"female": n, "male": n}}` over `GROUPS`.
    """
    p = (paramset or params()).values
    mortality, fertility, migration = _rate_by_group(p)
    survive = np.exp(-mortality * STEP_Y)
    grow = np.exp(migration * STEP_Y)
    pop = {s: np.array([float(base.get(g, {}).get(s, 0.0)) for g in GROUPS])
           for s in ("female", "male")}
    out = [_snapshot(0, pop)]
    for step in range(1, steps + 1):
        women_mid = (pop["female"] + pop["female"] * survive) / 2.0
        births = float((fertility * women_mid).sum() * STEP_Y)
        new = {}
        for sex, share in (("female", 1.0 - p["male_birth_share"]),
                           ("male", p["male_birth_share"])):
            moved = np.zeros(len(GROUPS))
            moved[1:] = pop[sex][:-1] * survive[:-1]
            moved[-1] += pop[sex][-1] * survive[-1]
            moved[0] = births * share * math.sqrt(survive[0])
            new[sex] = moved * grow
        pop = new
        out.append(_snapshot(step, pop))
    return out


def _snapshot(step: int, pop: Mapping[str, F]) -> dict[str, Any]:
    total = pop["female"] + pop["male"]
    young = total[:3].sum()
    old = total[13:].sum()
    working = total.sum() - young - old
    return {"year": step * STEP_Y, "total": float(total.sum()),
            "by_group": {g: {"female": float(pop["female"][i]), "male": float(pop["male"][i])}
                         for i, g in enumerate(GROUPS)},
            "dependency_ratio": float((young + old) / working) if working else math.nan}
