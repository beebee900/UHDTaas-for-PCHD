"""Explanation quality with Quantus (design 04, 4.6.3).

For a sample of outputs (200 per model per release) the workflow measures

- faithfulness: Faithfulness Correlation (Bhatt et al. 2020), higher is better;
- robustness: Max-Sensitivity (Yeh et al. 2019), lower is better;
- complexity: Complexity (Bhatt et al. 2020), the entropy of the attribution, lower is better.

The model is any scoring function over flat inputs (feature rows, or a waveform), wrapped
as a torch module for Quantus. Inputs are shaped `[N, 1, F]`.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import torch
from torch import nn

from ahdt.xai.types import Array
from atra import contracts as c

SAMPLE_SIZE = 200
RUNS = 20
SENSITIVITY_SAMPLES = 5
SENSITIVITY_RADIUS = 0.1
SECTION = "## Explanation quality"

type Scorer = Callable[[Array], Array]
type Attribute = Callable[[Array], Array]


class _Score(nn.Module):
    """A scoring function as a two-class torch model on `[N, 1, F]`."""

    def __init__(self, score: Scorer) -> None:
        super().__init__()
        self.score = score

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        p = torch.as_tensor(self.score(x.detach().numpy().astype(float).reshape(len(x), -1)),
                            dtype=torch.float32)
        return torch.stack([1.0 - p, p], dim=1)


@dataclass(frozen=True)
class Quality:
    faithfulness: float
    robustness: float
    complexity: float
    samples: int

    def contract(self) -> c.ExplanationQuality:
        return c.ExplanationQuality(faithfulness=self.faithfulness, robustness=self.robustness,
                                    complexity=self.complexity)


def evaluate(score: Scorer, x: Array, attribute: Attribute, *, runs: int = RUNS,
             samples: int = SENSITIVITY_SAMPLES) -> Quality:
    """Quality of `attribute` (rows `[N, F]` to attributions `[N, F]`) for `score` on the
    rows `x`."""
    import quantus

    n, f = x.shape
    x3 = x.astype(np.float32)[:, None, :]
    a3 = np.asarray(attribute(x), dtype=np.float32)[:, None, :]
    y = np.ones(n, dtype=int)
    model = _Score(score).eval()

    def explain(model: object, inputs: Array, targets: Array, **kw: object) -> Array:
        rows = np.asarray(inputs, dtype=float).reshape(len(inputs), -1)
        out: Array = np.asarray(attribute(rows), dtype=np.float64)[:, None, :]
        return out

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        faith = quantus.FaithfulnessCorrelation(
            nr_runs=runs, subset_size=max(1, min(f - 1, f // 3 or 1)), perturb_baseline="mean",
            similarity_func=quantus.similarity_func.correlation_pearson,
            disable_warnings=True, return_aggregate=False)(
            model=model, x_batch=x3, y_batch=y, a_batch=a3, channel_first=True, device="cpu")
        robust = quantus.MaxSensitivity(
            nr_samples=samples, lower_bound=SENSITIVITY_RADIUS,
            disable_warnings=True, return_aggregate=False)(
            model=model, x_batch=x3, y_batch=y, a_batch=None, explain_func=explain,
            channel_first=True, device="cpu")
        cplx = quantus.Complexity(disable_warnings=True, return_aggregate=False)(
            model=model, x_batch=x3, y_batch=y, a_batch=a3, channel_first=True, device="cpu")
    return Quality(float(np.nanmean(faith)), float(np.nanmean(robust)),
                   float(np.nanmean(cplx)), n)


def card_section(model_id: str, version: str, q: Quality, explainer: str) -> str:
    return "\n".join([
        SECTION, "", f"{explainer} on {q.samples} outputs of {model_id} {version}.", "",
        "| Metric | Value | Better |", "|---|---|---|",
        f"| Faithfulness correlation | {q.faithfulness:.3f} | higher |",
        f"| Max-sensitivity | {q.robustness:.3f} | lower |",
        f"| Complexity (entropy) | {q.complexity:.3f} | lower |", ""])


def write_to_card(card: Path, section: str) -> None:
    """Add the quality section to a model card, or replace the one already there."""
    text = card.read_text(encoding="utf-8")
    head = text.split(SECTION)[0].rstrip()
    card.write_text(f"{head}\n\n{section}", encoding="utf-8")
