"""Preference and values: multi-criteria decision analysis (design 05, 5.5.4).

Criteria weights come from a swing-weighting questionnaire (points for the swing from worst to
best on each criterion) or from paired choices (logistic regression on the attribute
differences). Options are scored by an additive value function over attributes scaled to
[0, 1] across the options, so a weight is the value of a full swing on that criterion.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import numpy as np

from apdt.models.context import param

CRITERIA = ("effectiveness", "side_effect_risk", "cost_to_patient", "doses_per_day", "route",
            "time_to_recovery", "travel")
HIGHER_IS_BETTER = {"effectiveness": True, "side_effect_risk": False, "cost_to_patient": False,
                    "doses_per_day": False, "route": False, "time_to_recovery": False,
                    "travel": False}


def swing_weights(points: Mapping[str, float]) -> dict[str, float]:
    """Normalised weights from swing points (the most important swing gets 100)."""
    unknown = set(points) - set(CRITERIA)
    if unknown:
        raise ValueError(f"unknown criteria: {sorted(unknown)}")
    if any(v < 0 for v in points.values()) or sum(points.values()) <= 0:
        raise ValueError("swing points must be non-negative with a positive sum")
    total = float(sum(points.values()))
    return {c: float(v) / total for c, v in points.items()}


@dataclass(frozen=True)
class PairedChoice:
    """Two options as attribute dictionaries (raw values) and the one chosen ('a' or 'b')."""

    a: Mapping[str, float]
    b: Mapping[str, float]
    chosen: str


def _scaled(options: Sequence[Mapping[str, float]], criteria: Sequence[str]
            ) -> list[dict[str, float]]:
    """Attribute values scaled to [0, 1] with 1 as the preferred end."""
    out: list[dict[str, float]] = [{} for _ in options]
    for c in criteria:
        vals = [o[c] for o in options if c in o]
        if len(vals) != len(options):
            continue
        lo, hi = min(vals), max(vals)
        for i, o in enumerate(options):
            x = 0.5 if hi == lo else (o[c] - lo) / (hi - lo)
            out[i][c] = x if HIGHER_IS_BETTER[c] else 1.0 - x
    return out


def paired_choice_weights(choices: Sequence[PairedChoice]) -> dict[str, float]:
    """Weights from paired choices. The choice probability is logistic in the weighted
    difference of the scaled attributes; negative coefficients are set to 0."""
    from sklearn.linear_model import LogisticRegression

    criteria = [c for c in CRITERIA if all(c in ch.a and c in ch.b for ch in choices)]
    if len(choices) < 2 or not criteria:
        raise ValueError("paired choices need at least two choices with shared criteria")
    rows, labels = [], []
    for ch in choices:
        a, b = _scaled([ch.a, ch.b], criteria)
        diff = [a[c] - b[c] for c in criteria]
        rows.append(diff)
        labels.append(1 if ch.chosen == "a" else 0)
        rows.append([-d for d in diff])
        labels.append(0 if ch.chosen == "a" else 1)
    clf = LogisticRegression(fit_intercept=False, C=1.0).fit(np.asarray(rows), labels)
    coef = np.clip(clf.coef_[0], 0.0, None)
    if coef.sum() <= 0:
        raise ValueError("the choices do not distinguish the criteria")
    return {c: float(w / coef.sum()) for c, w in zip(criteria, coef, strict=True)}


@dataclass(frozen=True)
class Scored:
    option_id: str
    value: float
    contributions: Mapping[str, float]


def score_options(weights: Mapping[str, float],
                  options: Mapping[str, Mapping[str, float]]) -> list[Scored]:
    """Options ordered by additive value. A criterion missing for any option is left out
    and its weight is renormalised over the criteria that remain."""
    ids = list(options)
    criteria = [c for c in weights if all(c in options[i] for i in ids)]
    if not criteria:
        raise ValueError("no criterion is available for every option")
    total = sum(weights[c] for c in criteria)
    scaled = _scaled([options[i] for i in ids], criteria)
    out = []
    for oid, s in zip(ids, scaled, strict=True):
        contrib = {c: weights[c] / total * s[c] for c in criteria}
        out.append(Scored(oid, float(sum(contrib.values())), contrib))
    return sorted(out, key=lambda x: -x.value)


def option_attributes(doses_per_day: float | None, route: str | None) -> dict[str, float]:
    """The attributes that the kb dose entry gives; the rest come from the caller."""
    attrs: dict[str, float] = {}
    if doses_per_day is not None:
        attrs["doses_per_day"] = float(doses_per_day)
    if route is not None:
        attrs["route"] = float(param("route_burden")[route])
    return attrs
