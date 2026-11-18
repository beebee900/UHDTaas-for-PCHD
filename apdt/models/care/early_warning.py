"""NEWS2 for adults and PEWS for children (design 05, 5.5.3), baselines of the deterioration
model. The scoring functions and kb tables are the AHDT early-warning model's
(`ahdt.whole_body.early_warning`), which this model pins in `depends_on`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ahdt.models.whole_body.early_warning import (
    NEWS2_INPUTS,
    news2,
    pews,
    pews_level,
    pews_table,
    response_band,
)
from apdt.models.context import kb

ACVPU = {"A": "alert", "C": "new_confusion", "V": "voice", "P": "pain", "U": "unresponsive"}


@dataclass(frozen=True)
class EarlyWarning:
    scale: str
    total: int
    band: str | None
    components: Mapping[str, int] = field(default_factory=dict)
    monitoring: Mapping[str, Any] | None = None


def score(vitals: Mapping[str, Any], age_years: float) -> EarlyWarning | None:
    """NEWS2 at or above the kb minimum age, else PEWS; None when a required vital sign
    is missing."""
    k = kb()
    vitals = {**vitals, "consciousness": ACVPU.get(str(vitals.get("consciousness")),
                                                    vitals.get("consciousness"))}
    table = k.entry("news2.scoring").content()
    if age_years >= float(table["min_age_years"]):
        if any(vitals.get(name) is None for name in NEWS2_INPUTS):
            return None
        components = news2(vitals, table)
        total = sum(components.values())
        band = response_band(total, components, k.resolve("news2.bands")["bands"])
        monitoring = next((b for b in k.entry("news2.monitoring").content()["bands"]
                           if b["band"] == band), None)
        return EarlyWarning("news2", total, band, components, monitoring)
    components_p = pews({**vitals}, pews_table(k, age_years),
                        k.entry("pews.scoring.common").content())
    if components_p is None:
        return None
    total = sum(components_p.values())
    level = pews_level(total, list(vitals.get("pews_triggers") or []),
                       k.entry("pews.escalation").content())
    return EarlyWarning("pews", total, level, components_p)
