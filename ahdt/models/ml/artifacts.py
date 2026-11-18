"""Artifact layout of a trained T1 model, shared by the laptop and the VM jobs.

One directory per model, `<root>/<model_id>/`:

- `metrics.json`: the validation result (dataset, metric, value, date), all metrics, the
  fairness slice report, the split, the file hashes and the edge specs
- `report.md`: the validation and fairness tables for the model card
- the model files (`model.*`), and for edge models `<name>.onnx` + `<name>.json` in the
  edge spec format of `edge/inference.py`

The laptop root is `var/models/t1`; the VM writes `$ATRA/out` and `pull.sh` copies it back.
This module imports only the standard library, so every job can use it.
"""

from __future__ import annotations

import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

LAPTOP_ROOT = Path(__file__).resolve().parents[3] / "var" / "models" / "t1"
METRICS = "metrics.json"
REPORT = "report.md"


def default_root() -> Path:
    """`$ATRA/out` on the VM (where `ATRA` is set), else `var/models/t1`."""
    atra = os.environ.get("ATRA")
    return Path(atra) / "out" if atra else LAPTOP_ROOT


def model_dir(model_id: str, root: Path | None = None) -> Path:
    return (root or default_root()) / model_id


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


@dataclass
class Result:
    """What a training job reports for one model."""

    model_id: str
    version: str
    dataset: str
    metric: str
    value: float
    metrics: dict[str, float] = field(default_factory=dict)
    fairness: Mapping[str, Any] | None = None
    split: Mapping[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    edge: list[Mapping[str, Any]] = field(default_factory=list)

    def validation(self) -> dict[str, Any]:
        return {"dataset": self.dataset, "metric": self.metric, "value": float(self.value),
                "date": datetime.now(UTC).date().isoformat()}


def write_result(result: Result, directory: Path, *, fairness_md: str = "",
                 extra_md: Sequence[str] = ()) -> Path:
    """Write metrics.json and report.md into the model directory (files already there)."""
    directory.mkdir(parents=True, exist_ok=True)
    files = {p.name: sha256(p) for p in sorted(directory.iterdir())
             if p.is_file() and p.name not in (METRICS, REPORT) and not p.name.startswith(".")}
    doc = {"model_id": result.model_id, "version": result.version,
           "trained_at": datetime.now(UTC).isoformat(timespec="seconds"),
           "validation": result.validation(), "metrics": result.metrics,
           "fairness": result.fairness, "split": dict(result.split), "notes": result.notes,
           "files": files, "edge": result.edge}
    path = directory / METRICS
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(doc, indent=1, sort_keys=True, default=float), encoding="utf-8")
    tmp.replace(path)
    v = result.validation()
    lines = [f"## Validation: {result.model_id} {result.version}", "",
             f"{v['dataset']}: {v['metric']} = {v['value']:.4g} ({v['date']}).", "",
             "| Metric | Value |", "|---|---|"]
    lines += [f"| {k} | {val:.4g} |" for k, val in sorted(result.metrics.items())]
    if result.split:
        lines += ["", "Split: " + ", ".join(f"{k} {val}" for k, val in result.split.items())
                  + "."]
    lines += ["", *[f"- {n}" for n in result.notes]] if result.notes else []
    lines += ["", *extra_md, "", fairness_md]
    (directory / REPORT).write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return path


def read_metrics(directory: Path) -> dict[str, Any] | None:
    path = directory / METRICS
    if not path.exists():
        return None
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def check_files(directory: Path, metrics: Mapping[str, Any]) -> list[str]:
    """Names of the recorded files that are missing or changed."""
    bad = []
    for name, digest in metrics.get("files", {}).items():
        p = directory / name
        if not p.exists() or sha256(p) != digest:
            bad.append(name)
    return bad
