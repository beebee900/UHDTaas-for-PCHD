"""Model cards (design 03, 3.4): the registry entry as a header, the parameter sources and
the open items for sign-off.

Run `python -m ahdt.models.cards` to write one card per model to
`docs/governance/model_cards/`.
"""

from __future__ import annotations

import argparse
from collections.abc import Mapping
from pathlib import Path

from ahdt.models.base import Layer4Base
from ahdt.models.catalogue import build_catalogue
from ahdt.models.params import ParamSet
from ahdt.models.validation import VALIDATORS, Check
from atra import contracts as c
from atra.config import ROOT

CARDS_DIR = ROOT / "docs" / "governance" / "model_cards"


def card(model: Layer4Base, check: Check | None = None) -> str:
    entry = model.spec.entry(model.paramset, check.validation() if check else None)
    return render(entry, model.paramset, model.spec.fidelity_note, check)


def render(entry: c.ModelRegistryEntry, paramset: ParamSet | None,
           fidelity_note: str | None = None, check: Check | None = None) -> str:
    lines = [f"# {entry.model_id}", "",
             "| Field | Value |", "|---|---|",
             f"| Version | {entry.version} |",
             f"| Twin | {getattr(entry.twin, 'value', entry.twin)} |",
             f"| Family | {entry.family.value} |",
             f"| Fidelity tier | {entry.tier.value} |",
             f"| Anatomy | {entry.anatomy or 'none'} |",
             f"| Intended use | {entry.intended_use} |",
             f"| Regulatory status | {entry.regulatory_status} |",
             f"| Source | {entry.source} |"]
    if fidelity_note:
        lines.append(f"| Fidelity note | {fidelity_note} |")
    if entry.validity:
        lines.append(f"| Validity | {entry.validity} |")
    if check is not None:
        status = "passed" if check.passed else "failed"
        lines.append(f"| Validation | {check.dataset}: {check.metric} = {check.value:.6g} "
                     f"(tolerance {check.tolerance:g}, {status}) |")
    lines += ["", "## Inputs", ""]
    lines += [f"- `{i.name}` ({i.unit}) from `{i.from_}`" for i in entry.inputs] or ["- none"]
    lines += ["", "## Outputs", ""]
    lines += [f"- `{o.name}` ({o.unit})" for o in entry.outputs]
    if paramset is not None:
        sources = {s.id: s for s in paramset.sources}
        lines += ["", "## Parameters", "", "| Name | Value | Unit | Source | Status |",
                  "|---|---|---|---|---|"]
        for name, param in paramset.params.items():
            status = ("assumption" if param.assumption else
                      "unverified" if not param.verified else "published")
            lines.append(f"| `{name}` | {param.value:g} | {param.unit} | {param.source} "
                         f"| {status} |")
        lines += ["", "## Sources", ""]
        lines += [f"- **{s.id}**: {s.citation}" + (f" Via: {s.via}." if s.via else "")
                  for s in sources.values()]
        open_items = [(n, p) for n, p in paramset.params.items()
                      if p.assumption or not p.verified]
        if open_items:
            lines += ["", "## Open items for sign-off", ""]
            lines += [f"- `{n}`: {p.justification}" for n, p in open_items]
    return "\n".join(lines) + "\n"


def write_cards(directory: Path = CARDS_DIR,
                catalogue: Mapping[str, Layer4Base] | None = None) -> list[Path]:
    models = catalogue or build_catalogue()
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for model_id, model in models.items():
        check = VALIDATORS[model_id](model) if model_id in VALIDATORS else None
        path = directory / f"{model_id}.md"
        path.write_text(card(model, check), encoding="utf-8")
        written.append(path)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="Write the Layer 4 model cards")
    parser.add_argument("--out", type=Path, default=CARDS_DIR)
    args = parser.parse_args()
    paths = write_cards(args.out)
    print(f"wrote {len(paths)} model cards to {args.out}")


if __name__ == "__main__":
    main()
