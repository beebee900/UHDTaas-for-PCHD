"""Cox proportional-hazards adherence model (lifelines) on refill-gap times.

Validation on held-out persons: Harrell's C-index, and the calibration at `horizon_d`
(the mean predicted probability of a refill gap against the Kaplan-Meier estimate).
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ahdt.models.ml.artifacts import Result, write_result
from ahdt.models.ml.common import split_masks
from evaluation.models.ahdt.fairness import ATTRIBUTES, concordance, slice_report

MODEL_FILE = "model.json"


def train(model_id: str, version: str, dataset: str, df: pd.DataFrame,
          covariates: Sequence[str], out: Path, *, duration: str = "duration_d",
          event: str = "event", horizon_d: float = 180.0) -> Result:
    from lifelines import CoxPHFitter, KaplanMeierFitter

    masks = split_masks(df.hdt_id.astype(str))
    cols = [*covariates, duration, event]
    cph = CoxPHFitter(penalizer=0.01)
    cph.fit(df.loc[masks["train"], cols], duration_col=duration, event_col=event)
    test = df[masks["test"]]
    risk = cph.predict_partial_hazard(test[list(covariates)]).to_numpy()
    c_index = concordance(test[duration], test[event], risk)
    surv = cph.predict_survival_function(test[list(covariates)], times=[horizon_d])
    predicted = float(1.0 - surv.to_numpy().mean())
    km = KaplanMeierFitter().fit(test[duration], test[event])
    observed = float(1.0 - km.predict(horizon_d))
    metrics = {"c_index": c_index, f"predicted_gap_{int(horizon_d)}d": predicted,
               f"observed_gap_{int(horizon_d)}d": observed,
               "calibration_error": abs(predicted - observed)}
    groups = {a: test[a].tolist() for a in ATTRIBUTES if a in test}
    report = slice_report(model_id, "survival",
                          np.column_stack([test[duration], test[event]]), risk, groups)
    out.mkdir(parents=True, exist_ok=True)
    params: dict[str, Any] = {
        "covariates": list(covariates), "coef": cph.params_.to_dict(),
        "means": cph._norm_mean.to_dict(),
        "baseline_survival": {"t": cph.baseline_survival_.index.tolist(),
                              "s": cph.baseline_survival_.iloc[:, 0].tolist()},
        "horizon_d": horizon_d}
    (out / MODEL_FILE).write_text(json.dumps(params, indent=1), encoding="utf-8")
    result = Result(model_id, version, dataset, "c_index", c_index, metrics,
                    report.to_dict(),
                    split={k: int(v.sum()) for k, v in masks.items()} | {"unit": "person"})
    write_result(result, out, fairness_md=report.markdown())
    return result


class Predictor:
    """Probability of a refill gap within `t` days for one covariate row."""

    def __init__(self, directory: Path) -> None:
        self.p = json.loads((directory / MODEL_FILE).read_text(encoding="utf-8"))

    def gap_probability(self, row: dict[str, float], t: float | None = None) -> float:
        t = float(self.p["horizon_d"] if t is None else t)
        lin = sum(self.p["coef"][c] * (float(row[c]) - self.p["means"][c])
                  for c in self.p["covariates"])
        times = np.asarray(self.p["baseline_survival"]["t"], dtype=float)
        h0 = -np.log(np.asarray(self.p["baseline_survival"]["s"], dtype=float))
        # Linear in the cumulative hazard between event times, as lifelines predicts.
        return float(1.0 - np.exp(-float(np.interp(t, times, h0)) * np.exp(lin)))
