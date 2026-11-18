"""Fairness slice tables of the T1 models (design 07, 7.5).

Each T1 model is evaluated per slice (sex, age band, region, facility level, preferred
language). A slice table holds per slice the model's performance metric, the expected
calibration error (ECE) and the conformal coverage, where the model has them. The
disparity of an attribute is the maximum minus the minimum over its slices with at least
`min_n` rows; a flag fires when the disparity exceeds 0.05 AUROC or 0.05 coverage.

Only numpy and scikit-learn are imported, so the training jobs on the VM use this module too.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray
from sklearn.metrics import f1_score, mean_absolute_error, roc_auc_score

type Task = Literal["binary", "multiclass", "regression", "survival"]

ATTRIBUTES = ("sex", "age_band", "region", "facility_level", "language")
FLAG_LIMITS = {"auroc": 0.05, "coverage": 0.05}
SYNTHETIC_NOTE = ("These numbers come from synthetic data. They test the reporting pipeline, "
                  "not real-world equity.")


def ece(y_true: ArrayLike, p: ArrayLike, bins: int = 10) -> float:
    """Expected calibration error of binary probabilities (equal-width bins)."""
    y = np.asarray(y_true, dtype=float)
    q = np.clip(np.asarray(p, dtype=float), 0.0, 1.0)
    edges = np.linspace(0.0, 1.0, bins + 1)
    idx = np.clip(np.digitize(q, edges[1:-1]), 0, bins - 1)
    total = 0.0
    for b in range(bins):
        mask = idx == b
        if mask.any():
            total += mask.mean() * abs(q[mask].mean() - y[mask].mean())
    return float(total)


def multiclass_ece(y_true: ArrayLike, proba: ArrayLike, bins: int = 10) -> float:
    """ECE of the top-class confidence."""
    pr = np.asarray(proba, dtype=float)
    y = np.asarray(y_true)
    return ece(pr.argmax(axis=1) == y, pr.max(axis=1), bins)


def concordance(time: ArrayLike, event: ArrayLike, risk: ArrayLike) -> float:
    """Harrell's C-index: share of comparable pairs ordered correctly by risk."""
    t = np.asarray(time, dtype=float)
    e = np.asarray(event, dtype=bool)
    r = np.asarray(risk, dtype=float)
    num = den = 0.0
    for i in np.flatnonzero(e):
        later = t > t[i]
        den += later.sum()
        num += (r[i] > r[later]).sum() + 0.5 * (r[i] == r[later]).sum()
    return float(num / den) if den else float("nan")


@dataclass
class SliceRow:
    attribute: str
    value: str
    n: int
    metric: float | None
    ece: float | None = None
    coverage: float | None = None


@dataclass
class FairnessReport:
    model_id: str
    task: Task
    metric: str
    rows: list[SliceRow]
    disparity: dict[str, dict[str, float]] = field(default_factory=dict)
    flags: list[str] = field(default_factory=list)
    unavailable: list[str] = field(default_factory=list)
    note: str = SYNTHETIC_NOTE
    min_n: int = 20

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> FairnessReport:
        rows = [SliceRow(**r) for r in data["rows"]]
        return cls(**{**data, "rows": rows})

    def markdown(self) -> str:
        lines = [f"### Fairness slices: {self.model_id}", "",
                 f"Metric: {self.metric}. Slices with fewer than {self.min_n} rows are "
                 "listed but not used for the disparity.", "",
                 f"| Attribute | Slice | n | {self.metric} | ECE | Coverage |",
                 "|---|---|---|---|---|---|"]
        for r in self.rows:
            lines.append(f"| {r.attribute} | {r.value} | {r.n} | {_fmt(r.metric)} | "
                         f"{_fmt(r.ece)} | {_fmt(r.coverage)} |")
        lines += ["", "| Attribute | Disparity |", "|---|---|"]
        for attr, d in self.disparity.items():
            lines.append(f"| {attr} | " + ", ".join(f"{k} {v:.3f}" for k, v in d.items()) + " |")
        if self.unavailable:
            lines += ["", "Not in this dataset: " + ", ".join(self.unavailable) + "."]
        lines += ["", "Flags: " + ("; ".join(self.flags) if self.flags else "none") + ".",
                  "", self.note, ""]
        return "\n".join(lines)


def _fmt(v: float | None) -> str:
    return "" if v is None or not np.isfinite(v) else f"{v:.3f}"


def _metric_fn(task: Task) -> tuple[str, Callable[..., float]]:
    if task == "binary":
        return "auroc", lambda y, s: float(roc_auc_score(y, s))
    if task == "multiclass":
        return "macro_f1", lambda y, s: float(f1_score(y, np.asarray(s).argmax(axis=1),
                                                       average="macro"))
    if task == "regression":
        return "mae", lambda y, s: float(mean_absolute_error(y, s))
    return "c_index", lambda y, s: concordance(y[:, 0], y[:, 1], s)


def _safe(fn: Callable[..., float], *args: Any) -> float | None:
    try:
        v = fn(*args)
    except ValueError:
        return None
    return v if np.isfinite(v) else None


def slice_report(model_id: str, task: Task, y_true: ArrayLike, score: ArrayLike,
                 groups: Mapping[str, Sequence[Any] | NDArray[Any]], *,
                 covered: ArrayLike | None = None, min_n: int = 20,
                 flag_limits: Mapping[str, float] = FLAG_LIMITS) -> FairnessReport:
    """Per-slice table.

    `score`: binary probabilities, class probabilities (n, k), regression predictions, or
    survival risk scores with `y_true` = (n, 2) [time, event]. `covered`: per-row booleans,
    true where the conformal interval or set holds the true value.
    """
    name, metric = _metric_fn(task)
    y = np.asarray(y_true)
    s = np.asarray(score)
    cov = None if covered is None else np.asarray(covered, dtype=bool)
    rows: list[SliceRow] = []
    disparity: dict[str, dict[str, float]] = {}
    flags: list[str] = []
    unavailable = [a for a in ATTRIBUTES if a not in groups]
    for attr, values in groups.items():
        v = np.asarray([str(x) for x in values])
        kept: dict[str, list[float]] = {name: [], "coverage": []}
        for value in sorted(set(v)):
            m = v == value
            row = SliceRow(attr, value, int(m.sum()), _safe(metric, y[m], s[m]))
            if task == "binary":
                row.ece = ece(y[m], s[m])
            elif task == "multiclass":
                row.ece = multiclass_ece(y[m], s[m])
            if cov is not None:
                row.coverage = float(cov[m].mean())
            rows.append(row)
            if row.n >= min_n:
                if row.metric is not None:
                    kept[name].append(row.metric)
                if row.coverage is not None:
                    kept["coverage"].append(row.coverage)
        d = {k: float(max(vals) - min(vals)) for k, vals in kept.items() if len(vals) >= 2}
        disparity[attr] = d
        for key, limit in flag_limits.items():
            if key in d and d[key] > limit:
                flags.append(f"{attr}: {key} disparity {d[key]:.3f} > {limit}")
    return FairnessReport(model_id, task, name, rows, disparity, flags, unavailable,
                          min_n=min_n)
