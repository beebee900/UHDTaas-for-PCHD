"""River online baselines per person with anomaly flags (lifestyle).

Each person and field keeps a River exponentially weighted mean and variance. A day's
anomaly score is the largest absolute z-score over the fields, computed before the day is
learned. The fading factor is chosen on the training persons, the flag threshold on the
calibration persons, and the AUROC is measured on the test persons.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.metrics import roc_auc_score

from ahdt.models.ml.artifacts import Result, write_result
from ahdt.models.ml.common import operating_point, sensitivity_specificity, split_masks
from evaluation.models.ahdt.fairness import ATTRIBUTES, ece, slice_report

MODEL_FILE = "model.json"
WARMUP = 14
FADING = (0.05, 0.1, 0.2, 0.3)


class Baseline:
    """One person's online baseline over `fields`."""

    def __init__(self, fields: Sequence[str], fading: float) -> None:
        from river import stats

        self.fields = list(fields)
        self.mean = {f: stats.EWMean(fading_factor=fading) for f in fields}
        self.var = {f: stats.EWVar(fading_factor=fading) for f in fields}
        self.n = 0

    def score(self, x: Mapping[str, float]) -> dict[str, float]:
        if self.n < 2:
            return {f: 0.0 for f in self.fields}
        out = {}
        for f in self.fields:
            sd = float(np.sqrt(max(self.var[f].get(), 1e-9)))
            out[f] = abs(float(x[f]) - float(self.mean[f].get())) / sd
        return out

    def learn(self, x: Mapping[str, float]) -> None:
        for f in self.fields:
            self.mean[f].update(float(x[f]))
            self.var[f].update(float(x[f]))
        self.n += 1


def scores(df: pd.DataFrame, fields: Sequence[str], fading: float) -> NDArray[np.float64]:
    out = np.zeros(len(df))
    pos = {idx: i for i, idx in enumerate(df.index)}
    for _, g in df.groupby("hdt_id"):
        b = Baseline(fields, fading)
        for idx, row in g.sort_values("day").iterrows():
            out[pos[idx]] = max(b.score(row).values())
            b.learn(row)
    return out


def train(model_id: str, version: str, dataset: str, df: pd.DataFrame,
          fields: Sequence[str], out: Path) -> Result:
    masks = split_masks(df.hdt_id.astype(str))
    after = (df.day >= WARMUP).to_numpy()
    y = df.label.to_numpy()
    best = max(FADING, key=lambda a: roc_auc_score(
        y[masks["train"] & after], scores(df[masks["train"]], fields, a)[after[masks["train"]]]))
    s = scores(df, fields, best)
    cal = masks["cal"] & after
    test = masks["test"] & after
    threshold = operating_point(y[cal], s[cal], min_sensitivity=0.8)
    sens, spec = sensitivity_specificity(y[test], s[test], threshold)
    auroc = float(roc_auc_score(y[test], s[test]))
    p = 1.0 - np.exp(-np.maximum(s, 0.0) / threshold * np.log(2.0))
    metrics = {"auroc": auroc, "fading_factor": best, "flag_threshold_z": threshold,
               "sensitivity": sens, "specificity": spec, "ece_score_map": ece(y[test], p[test])}
    t = df[test]
    groups = {a: t[a].tolist() for a in ATTRIBUTES if a in t}
    report = slice_report(model_id, "binary", y[test], p[test], groups)
    out.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {"fields": list(fields), "fading_factor": best,
                            "threshold_z": threshold, "warmup_days": WARMUP}
    (out / MODEL_FILE).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    result = Result(model_id, version, dataset, "auroc", auroc, metrics, report.to_dict(),
                    split={k: int(v.sum()) for k, v in masks.items()} | {"unit": "person-day"},
                    notes=["ECE and the slice table use the score mapped to (0, 1) with 0.5 at "
                           "the flag threshold; the score is not a calibrated probability."])
    write_result(result, out, fairness_md=report.markdown())
    return result
