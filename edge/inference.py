"""ONNX Runtime host for the edge models (design 04, 4.2.1 tier 2): arrhythmia, desaturation and
fall detection, trained and exported by `ahdt/models/ml` (WP14b).

Each model is a pair of files in the models directory: `<name>.onnx` and `<name>.json`, its
edge spec. The spec fixes the input the edge builds and the output it reads:

```json
{"model_id": "ahdt.respiratory.desaturation_detection", "version": "1.0.0",
 "file": "desaturation.onnx",
 "input": {"name": "x", "kind": "features",
           "features": ["spo2.mean", "spo2.min", "heart_rate.mean"]},
 "output": {"name": "p", "labels": ["normal", "desaturation"]},
 "alert": {"label": "desaturation", "min_probability": 0.5, "urgency": "urgent"}}
```

- `kind: features`: a float32 tensor `[1, len(features)]`. A feature is `<field>.<stat>` of
  one closed feature window of the person (`stat` is `mean`, `min`, `max` or `n`; `field` is
  the twin field name of `ahdt/registry`). A window without every feature is skipped.
- `kind: waveform`: `{"field": "ecg_lead_ii", "fs": 250, "samples": 2500}`, the last `samples`
  values of a waveform of that field at that rate, as `[1, samples]` or, for a rank-3 input,
  `[1, 1, samples]`.
- The output is a probability per label, `[1, len(labels)]`. `alert` is the operating point
  chosen at validation: the detection raises an alert when the probability of `label` is at
  least `min_probability`.
"""

from __future__ import annotations

import json
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field

from ahdt.ingest.fields import FieldIndex, field_index
from atra.contracts import Code
from edge.preprocess import FeatureWindow

STATS = ("mean", "min", "max", "n")


class InputSpec(BaseModel):
    name: str
    kind: Literal["features", "waveform"]
    features: list[str] = Field(default_factory=list)
    field: str | None = None
    fs: float | None = Field(None, gt=0)
    samples: int | None = Field(None, gt=0)


class OutputSpec(BaseModel):
    name: str
    labels: list[str] = Field(min_length=1)


class AlertSpec(BaseModel):
    label: str
    min_probability: float = Field(ge=0, le=1)
    urgency: Literal["emergency", "urgent", "routine"]


class EdgeModelSpec(BaseModel):
    model_id: str
    version: str
    file: str
    input: InputSpec
    output: OutputSpec
    alert: AlertSpec | None = None


@dataclass(frozen=True)
class Detection:
    model_id: str
    version: str
    hdt_id: str
    time: datetime
    probabilities: Mapping[str, float]
    alert: AlertSpec | None

    @property
    def fires(self) -> bool:
        a = self.alert
        return a is not None and self.probabilities.get(a.label, 0.0) >= a.min_probability


class EdgeModel:
    def __init__(self, spec: EdgeModelSpec, model: bytes | Path) -> None:
        import onnxruntime as ort

        self.spec = spec
        options = ort.SessionOptions()
        options.intra_op_num_threads = 1
        options.inter_op_num_threads = 1
        source = str(model) if isinstance(model, Path) else model
        self.session = ort.InferenceSession(source, options, providers=["CPUExecutionProvider"])
        inputs = {i.name: i for i in self.session.get_inputs()}
        if spec.input.name not in inputs:
            raise ValueError(f"{spec.model_id}: the model has no input {spec.input.name}")
        self.rank = len(inputs[spec.input.name].shape)
        if spec.input.kind == "waveform" and not (spec.input.field and spec.input.fs
                                                  and spec.input.samples):
            raise ValueError(f"{spec.model_id}: a waveform input names field, fs and samples")
        if spec.alert and spec.alert.label not in spec.output.labels:
            raise ValueError(f"{spec.model_id}: alert label {spec.alert.label} is not an output")

    def run(self, x: Sequence[float]) -> dict[str, float]:
        arr = np.asarray(x, dtype=np.float32).reshape((1,) * (self.rank - 1) + (-1,))
        (out,) = self.session.run([self.spec.output.name], {self.spec.input.name: arr})
        probs = np.asarray(out, dtype=float).reshape(-1)
        if probs.size != len(self.spec.output.labels):
            raise ValueError(f"{self.spec.model_id}: {probs.size} outputs for "
                             f"{len(self.spec.output.labels)} labels")
        return dict(zip(self.spec.output.labels, map(float, probs), strict=True))

    def detection(self, hdt_id: str, time: datetime, x: Sequence[float]) -> Detection:
        return Detection(self.spec.model_id, self.spec.version, hdt_id, time, self.run(x),
                         self.spec.alert)


def _stat(w: FeatureWindow, stat: str) -> float:
    return float(w.n) if stat == "n" else float(getattr(w, stat))


class OnnxHost:
    """Loads every edge model in a directory and runs them on pre-processed data."""

    def __init__(self, models: Iterable[EdgeModel] = (), *,
                 index: FieldIndex | None = None) -> None:
        self.models = {m.spec.model_id: m for m in models}
        self.index = index or field_index()

    @classmethod
    def from_dir(cls, directory: Path) -> OnnxHost:
        models = []
        if directory.is_dir():
            for spec_path in sorted(directory.glob("*.json")):
                spec = EdgeModelSpec.model_validate(json.loads(spec_path.read_text()))
                models.append(EdgeModel(spec, directory / spec.file))
        return cls(models)

    def add(self, model: EdgeModel) -> None:
        self.models[model.spec.model_id] = model

    def _field(self, code: Mapping[str, Any]) -> str | None:
        ref = self.index.resolve(Code.model_validate(dict(code)))
        return ref.field.name if ref else None

    def on_features(self, windows: Iterable[FeatureWindow]) -> list[Detection]:
        table: dict[tuple[str, datetime], dict[str, float]] = defaultdict(dict)
        for w in windows:
            if (name := self._field(w.code)) is not None:
                row = table[(w.hdt_id, w.start)]
                row.update({f"{name}.{s}": _stat(w, s) for s in STATS})
        out = []
        for m in self.models.values():
            if m.spec.input.kind != "features":
                continue
            for (hdt_id, start), row in sorted(table.items()):
                if all(f in row for f in m.spec.input.features):
                    out.append(m.detection(hdt_id, start,
                                           [row[f] for f in m.spec.input.features]))
        return out

    def on_waveforms(self, payloads: Iterable[Mapping[str, Any]]) -> list[Detection]:
        out = []
        for p in payloads:
            if not isinstance(p["value"], Mapping):
                continue
            name = self._field(p["code"])
            fs = 1000.0 / float(p["value"]["period_ms"])
            samples = p["value"]["array"]
            for m in self.models.values():
                spec = m.spec.input
                if (spec.kind != "waveform" or spec.field != name or spec.fs is None
                        or spec.samples is None or not math.isclose(fs, spec.fs, rel_tol=1e-6)
                        or len(samples) < spec.samples):
                    continue
                time = datetime.fromisoformat(str(p["effective_time"]))
                out.append(m.detection(str(p["hdt_id"]), time, samples[-spec.samples:]))
        return out
