"""Register the trained T1 models, install the edge models and write the model cards.

    python -m ahdt.models.ml register [--root var/models/t1] [--edge-dir var/models/edge]

For every T1 model with an artifact directory under `root` (written by a laptop job or
pulled from the VM by `vm/pull.sh`): check the recorded file hashes, register the entry
with its validation and metrics (fairness disparities and flag count included), copy the
edge models to `edge-dir`, and write `docs/governance/model_cards/<model_id>.md`. Models
without an artifact are listed as not trained; that is not an error.
"""

from __future__ import annotations

import json
import shutil
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ahdt.models.ml.artifacts import LAPTOP_ROOT, REPORT, check_files, read_metrics
from ahdt.models.ml.inventory import ITEMS, T1Item
from atra import contracts as c
from atra.backends.base import ModelRegistryBackend
from atra.config import ROOT

EDGE_DIR = ROOT / "var" / "models" / "edge"
CARDS_DIR = ROOT / "docs" / "governance" / "model_cards"


@dataclass
class Status:
    model_id: str
    state: str
    detail: str = ""


def flat_metrics(m: Mapping[str, Any]) -> dict[str, float]:
    out = {k: float(v) for k, v in m.get("metrics", {}).items()}
    fair = m.get("fairness") or {}
    for attr, d in fair.get("disparity", {}).items():
        for key, v in d.items():
            out[f"fairness.{attr}.{key}_disparity"] = float(v)
    out["fairness.flags"] = float(len(fair.get("flags", [])))
    return out


def entry_for(item: T1Item, m: Mapping[str, Any]) -> c.ModelRegistryEntry:
    validation = c.Validation(**m["validation"])
    entry = item.spec.entry(None, validation)
    return entry.model_copy(update={"version": str(m.get("version", entry.version))})


def install_edge(directory: Path, m: Mapping[str, Any], edge_dir: Path) -> list[str]:
    names = []
    for spec in m.get("edge", []):
        edge_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(directory / spec["file"], edge_dir / spec["file"])
        stem = Path(spec["file"]).stem
        (edge_dir / f"{stem}.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
        names.append(stem)
    return names


def card(item: T1Item, entry: c.ModelRegistryEntry | None, directory: Path) -> str:
    spec = item.spec
    lines = [f"# {spec.model_id}", "", "| Field | Value |", "|---|---|",
             f"| Version | {entry.version if entry else spec.version} |",
             f"| Twin | {spec.twin.value} |", f"| Family | {spec.family.value} |",
             f"| Fidelity tier | {spec.tier.value} |",
             f"| Intended use | {spec.intended_use} |",
             "| Regulatory status | research |", f"| Source | {spec.source} |",
             f"| Training data | {item.dataset} ({item.runs_on}) |"]
    if entry and entry.validation:
        v = entry.validation
        lines.append(f"| Validation | {v.dataset}: {v.metric} = {v.value:.4g} ({v.date}) |")
    else:
        lines.append("| Validation | not trained yet |")
    if spec.depends_on:
        lines.append("| Depends on | " + ", ".join(f"{m} {v}" for m, v in spec.depends_on) + " |")
    lines += ["", "## Inputs", "", *[f"- `{p.name}` ({p.unit})" for p in spec.inputs],
              "", "## Outputs", "", *[f"- `{p.name}` ({p.unit})" for p in spec.outputs], ""]
    report = directory / REPORT
    if report.exists():
        lines += [report.read_text(encoding="utf-8").replace("## Validation", "## Validation "
                                                             "report", 1)]
    return "\n".join(lines).rstrip() + "\n"


def write_card(cards_dir: Path, item: T1Item, entry: c.ModelRegistryEntry | None,
               directory: Path) -> None:
    cards_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / f"{item.spec.model_id}.md").write_text(card(item, entry, directory),
                                                         encoding="utf-8")


async def register(backend: ModelRegistryBackend, *, root: Path = LAPTOP_ROOT,
                   edge_dir: Path = EDGE_DIR, cards_dir: Path | None = CARDS_DIR
                   ) -> list[Status]:
    out = []
    for item in ITEMS:
        d = root / item.spec.model_id
        m = read_metrics(d)
        entry = None
        if m is None:
            out.append(Status(item.spec.model_id, "not trained", item.runs_on))
        elif bad := check_files(d, m):
            out.append(Status(item.spec.model_id, "artifact mismatch", ", ".join(bad)))
        else:
            entry = entry_for(item, m)
            await backend.register(entry, metrics=flat_metrics(m))
            edge = install_edge(d, m, edge_dir)
            v = m["validation"]
            out.append(Status(item.spec.model_id, "registered",
                              f"{v['metric']}={v['value']:.4g}"
                              + (f"; edge: {', '.join(edge)}" if edge else "")))
        if cards_dir is not None:
            write_card(cards_dir, item, entry, d)
    return out
