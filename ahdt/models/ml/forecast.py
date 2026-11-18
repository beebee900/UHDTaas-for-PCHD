"""Darts N-BEATS forecasters with split-conformal bands (BP, glucose, NEWS2 components).

One global model is fitted over the training persons' series. Validation forecasts the last
`horizon` steps of every held-out person's series from the `history` steps before them. The
conformal half-width of each output and horizon step comes from the calibration persons'
absolute errors; coverage is measured on the test persons. The naive last-value forecast is
reported as a baseline.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from ahdt.models.ml import conformal
from ahdt.models.ml.artifacts import Result, write_result
from ahdt.models.ml.common import split_of
from evaluation.models.ahdt.fairness import ATTRIBUTES, slice_report

type F = NDArray[np.float64]

LEVEL = 0.9
META_FILE = "model.json"
MODEL_FILE = "model.pt"
SCALER_FILE = "scaler.json"


@dataclass
class ForecastTask:
    model_id: str
    version: str
    dataset: str
    columns: Sequence[str]
    history: int
    horizon: int
    order: str = "t"
    group: str = "hdt_id"
    epochs: int = 15
    width: int = 64
    max_samples_per_ts: int = 24
    notes: Sequence[str] = field(default_factory=tuple)


class StandardScale:
    """Per-column standardisation fitted on the training series."""

    def __init__(self, mean: F, std: F) -> None:
        self.mean, self.std = mean, std

    @classmethod
    def fit(cls, arrays: Sequence[F]) -> StandardScale:
        a = np.concatenate(arrays)
        return cls(a.mean(axis=0), a.std(axis=0) + 1e-9)

    def apply(self, a: F) -> F:
        out: F = (a - self.mean) / self.std
        return out

    def invert(self, a: F) -> F:
        out: F = a * self.std + self.mean
        return out

    def to_dict(self) -> dict[str, list[float]]:
        return {"mean": self.mean.tolist(), "std": self.std.tolist()}

    @classmethod
    def from_dict(cls, d: dict[str, list[float]]) -> StandardScale:
        return cls(np.asarray(d["mean"]), np.asarray(d["std"]))


def _arrays(df: pd.DataFrame, task: ForecastTask) -> dict[str, F]:
    return {str(h): g.sort_values(task.order)[list(task.columns)].to_numpy(dtype=np.float32)
            for h, g in df.groupby(task.group)}


def _model(task: ForecastTask) -> Any:
    from darts.models import NBEATSModel

    return NBEATSModel(
        input_chunk_length=task.history, output_chunk_length=task.horizon,
        generic_architecture=True, num_stacks=4, num_blocks=1, num_layers=2,
        layer_widths=task.width, n_epochs=task.epochs, batch_size=256, random_state=7,
        pl_trainer_kwargs={"accelerator": "cpu", "enable_progress_bar": False,
                           "logger": False, "enable_checkpointing": False,
                           "enable_model_summary": False})


def _series(a: F) -> Any:
    from darts import TimeSeries

    return TimeSeries.from_values(a.astype(np.float32))


def _forecast(model: Any, histories: Sequence[NDArray[Any]], scale: StandardScale,
              horizon: int) -> F:
    preds = model.predict(n=horizon, series=[_series(scale.apply(h)) for h in histories],
                          verbose=False)
    return np.stack([scale.invert(p.values()) for p in preds])


def train(task: ForecastTask, df: pd.DataFrame, out: Path) -> Result:
    arrays = _arrays(df, task)
    need = task.history + task.horizon
    arrays = {h: a for h, a in arrays.items() if len(a) >= need}
    split = {h: split_of(h) for h in arrays}
    train_ids = [h for h, s in split.items() if s == "train"]
    scale = StandardScale.fit([arrays[h][:-task.horizon] for h in train_ids])
    model = _model(task)
    model.fit([_series(scale.apply(arrays[h])) for h in train_ids],
              max_samples_per_ts=task.max_samples_per_ts, verbose=False)

    def evaluate(kind: str) -> tuple[list[str], F, F, F]:
        ids = [h for h, s in split.items() if s == kind]
        hist = [arrays[h][-need:-task.horizon] for h in ids]
        truth = np.stack([arrays[h][-task.horizon:] for h in ids])
        naive = np.stack([np.repeat(x[-1:], task.horizon, axis=0) for x in hist])
        return ids, _forecast(model, hist, scale, task.horizon), truth, naive

    _, pred_cal, y_cal, _ = evaluate("cal")
    test_ids, pred_test, y_test, naive_test = evaluate("test")
    # (step, column) half-widths from the calibration persons
    half = np.array([[conformal.regression_halfwidth(y_cal[:, s, c], pred_cal[:, s, c], LEVEL)
                      for c in range(len(task.columns))] for s in range(task.horizon)])
    covered = conformal.interval_covers(y_test, pred_test, half[None, :, :])
    mae = np.abs(pred_test - y_test).mean(axis=(0, 1))
    naive_mae = np.abs(naive_test - y_test).mean(axis=(0, 1))
    metrics: dict[str, float] = {}
    for c, col in enumerate(task.columns):
        metrics[f"mae.{col}"] = float(mae[c])
        metrics[f"naive_mae.{col}"] = float(naive_mae[c])
        metrics[f"coverage_90.{col}"] = float(covered[:, :, c].mean())
        metrics[f"halfwidth_90_last_step.{col}"] = float(half[-1, c])
    first = task.columns[0]
    person_slices = df.drop_duplicates(task.group).set_index(task.group)
    groups = {a: [person_slices.loc[h, a] for h in test_ids] for a in ATTRIBUTES
              if a in person_slices}
    report = slice_report(task.model_id, "regression", y_test[:, :, 0].mean(axis=1),
                          pred_test[:, :, 0].mean(axis=1), groups,
                          covered=covered[:, :, 0].all(axis=1))
    out.mkdir(parents=True, exist_ok=True)
    model.save(str(out / MODEL_FILE))
    meta = {"columns": list(task.columns), "history": task.history, "horizon": task.horizon,
            "level": LEVEL, "halfwidth": half.tolist(), "scale": scale.to_dict()}
    (out / META_FILE).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    result = Result(task.model_id, task.version, task.dataset, f"mae.{first}",
                    metrics[f"mae.{first}"], metrics,
                    report.to_dict(),
                    split={k: sum(v == k for v in split.values()) for k in ("train", "cal", "test")}
                    | {"unit": "person"},
                    notes=[*task.notes, "Fairness rows use the mean forecast of the first output "
                           "over the horizon; coverage counts a person when every step of "
                           "the first output is inside its band."])
    write_result(result, out, fairness_md=report.markdown())
    return result


class Predictor:
    """Runtime form: forecast the next `horizon` steps with conformal bands."""

    def __init__(self, directory: Path) -> None:
        from darts.models import NBEATSModel

        self.meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
        self.model = NBEATSModel.load(str(directory / MODEL_FILE),
                                      pl_trainer_kwargs={"accelerator": "cpu",
                                                         "enable_progress_bar": False,
                                                         "logger": False})
        self.scale = StandardScale.from_dict(self.meta["scale"])

    def forecast(self, history: F) -> dict[str, Any]:
        h = int(self.meta["history"])
        a = np.asarray(history, dtype=np.float32).reshape(-1, len(self.meta["columns"]))
        if len(a) < h:
            raise ValueError(f"needs {h} past values, got {len(a)}")
        pred = _forecast(self.model, [a[-h:]], self.scale, int(self.meta["horizon"]))[0]
        half = np.asarray(self.meta["halfwidth"])
        return {"mean": pred, "lower": pred - half, "upper": pred + half,
                "level": float(self.meta["level"])}
