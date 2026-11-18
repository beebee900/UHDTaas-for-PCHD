"""Register the APDT Layer 4 models with their validation and write the model cards.

    python -m evaluation.models.apdt.register [--root DIR] [--no-cards]

A trained model takes its validation and fairness report from `<root>/<model_id>/metrics.json`
(written by `train`, `care` and `distill`). The rule-based models are validated on the six
persona scenarios. A model without either is registered with no validation and its card says
so.
"""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ahdt.models.ml.artifacts import REPORT, check_files, read_metrics
from apdt.models.diagnosis.comparator import APDT_ROOT
from apdt.models.reasoning import ClinicalReasoner
from apdt.models.registry import MODELS, APDTModel
from atra import contracts as c
from atra.backends.base import ModelRegistryBackend
from atra.config import ROOT
from evaluation.models.apdt.scenarios import SCENARIOS

CARDS_DIR = ROOT / "docs" / "governance" / "model_cards"
SCENARIO_DATASET = "six persona scenarios (evaluation/models/apdt/scenarios.py)"


@dataclass
class Status:
    model_id: str
    state: str
    detail: str = ""


def scenario_validations() -> dict[str, tuple[c.Validation, str]]:
    """Validation of the rule-based models on the persona scenarios, with the table rows."""
    reasoner = ClinicalReasoner()
    today = datetime.now(UTC).date().isoformat()
    top = first = issues = excluded_ok = 0
    expected_issues = 0
    rows = ["| Persona | Top diagnosis | Expected | First option | Expected |",
            "|---|---|---|---|---|"]
    for s in SCENARIOS:
        a = reasoner.assess(s.patient, s.observations, with_tests=False)
        listed = a.listing.listed[0].condition if a.listing and a.listing.listed else "none"
        option = a.first_option()
        got = option.option_id if option else "none"
        top += listed == s.expected_top
        first += got == s.expected_first_option
        found = {i.ix_id for i in a.issues}
        expected_issues += len(s.expected_issues)
        issues += len(set(s.expected_issues) & found)
        excluded_ok += not (a.listing and a.listing.excluded)
        rows.append(f"| {s.key} | {listed} | {s.expected_top} | {got} | "
                    f"{s.expected_first_option} |")
    n = len(SCENARIOS)
    table = "\n".join(rows)

    def v(metric: str, value: float) -> tuple[c.Validation, str]:
        return c.Validation(dataset=SCENARIO_DATASET, metric=metric, value=value,
                            date=today), table

    return {
        "apdt.diagnosis.differential_bn": v("top_diagnosis_agreement", top / n),
        "apdt.diagnosis.neuro_symbolic": v("top_diagnosis_agreement", top / n),
        "apdt.treatment.options": v("first_option_concordance", first / n),
        "apdt.treatment.dosing": v("first_option_concordance", first / n),
        "apdt.treatment.safety": v("expected_issue_recall",
                                   issues / expected_issues if expected_issues else 1.0)}


def trained_validation(model_id: str, root: Path
                       ) -> tuple[c.Validation, dict[str, float], str] | None:
    directory = root / model_id
    m = read_metrics(directory)
    if m is None or check_files(directory, m):
        return None
    report = directory / REPORT
    return (c.Validation(**m["validation"]), {k: float(x) for k, x in m["metrics"].items()},
            report.read_text(encoding="utf-8") if report.exists() else "")


def card(model: APDTModel, validation: c.Validation | None, extra: str = "") -> str:
    lines = [f"# {model.model_id}", "", "| Field | Value |", "|---|---|",
             f"| Version | {model.version} |", "| Twin | apdt |",
             f"| Family | {model.family.value} |", f"| Fidelity tier | {model.tier.value} |",
             f"| Intended use | {model.intended_use} |", "| Regulatory status | research |",
             f"| Source | {model.source} |"]
    if validation:
        lines.append(f"| Validation | {validation.dataset}: {validation.metric} = "
                     f"{validation.value:.4g} ({validation.date}) |")
    else:
        lines.append("| Validation | not validated yet |")
    if model.depends_on:
        lines.append("| Depends on | " + ", ".join(f"{m} {v}" for m, v in model.depends_on)
                     + " |")
    lines += ["", "## Inputs", "", *[f"- `{n}` ({u})" for n, u, _ in model.inputs],
              "", "## Outputs", "", *[f"- `{n}` ({u})" for n, u in model.outputs], ""]
    if extra:
        lines += [extra.replace("## Validation", "## Validation report", 1)]
    return "\n".join(lines).rstrip() + "\n"


def write_card(cards_dir: Path, model: APDTModel, validation: c.Validation | None,
               extra: str) -> None:
    cards_dir.mkdir(parents=True, exist_ok=True)
    (cards_dir / f"{model.model_id}.md").write_text(card(model, validation, extra),
                                                      encoding="utf-8")


async def register(backend: ModelRegistryBackend, *, root: Path = APDT_ROOT,
                   cards_dir: Path | None = CARDS_DIR) -> list[Status]:
    scenario = scenario_validations()
    out = []
    for model in MODELS:
        validation: c.Validation | None = None
        metrics: Mapping[str, float] | None = None
        extra = ""
        trained = trained_validation(model.model_id, root)
        if trained is not None:
            validation, metrics, extra = trained
        elif model.model_id in scenario:
            validation, extra = scenario[model.model_id]
            extra = "## Validation\n\nPersona scenarios.\n\n" + extra
        await backend.register(model.entry(validation), metrics=metrics)
        if cards_dir is not None:
            write_card(cards_dir, model, validation, extra)
        out.append(Status(model.model_id, "validated" if validation else "registered",
                          f"{validation.metric}={validation.value:.4g}" if validation else ""))
    return out


def main(argv: list[str] | None = None) -> int:
    import argparse

    from atra.backends import Backends
    from atra.config import get_settings

    parser = argparse.ArgumentParser(prog="python -m evaluation.models.apdt.register")
    parser.add_argument("--root", type=Path, default=APDT_ROOT)
    parser.add_argument("--no-cards", action="store_true")
    args = parser.parse_args(argv)

    async def run() -> list[Status]:
        backends = Backends(get_settings(), "apdt")
        try:
            return await register(backends.models, root=args.root,
                                  cards_dir=None if args.no_cards else CARDS_DIR)
        finally:
            await backends.close()

    for st in asyncio.run(run()):
        print(f"{st.model_id}: {st.state} {st.detail}".rstrip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
