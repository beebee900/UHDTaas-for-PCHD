"""Shared types of the AHDT explainable-AI layer (design 04, 4.6).

An explainer takes a `Subject` (the model, the instance to explain and the data an
explainer needs) and returns a `Result`. `to_explanation` turns a result into the
`AHDTExplanation` contract.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

import numpy as np
from numpy.typing import NDArray

from atra import contracts as c
from atra.ids import uuid7

type Array = NDArray[np.float64]
type MethodFamily = Literal["attribution", "saliency", "counterfactual", "sensitivity",
                            "rule_trace", "ontology_justification", "citation",
                            "temporal_attribution", "graph"]

KINDS = ("tabular", "forecast", "sequence", "online", "signal", "graph", "mechanistic",
         "rules", "reference", "text")


class Subject(Protocol):
    """What every explainer receives."""

    model_id: str
    version: str
    kind: str


@dataclass
class Result:
    """The outcome of one explainer run."""

    explainer: str
    family: MethodFamily
    drivers: list[c.Driver] = field(default_factory=list)
    output: float | None = None
    base: float | None = None
    uncertainty: dict[str, Any] = field(default_factory=dict)
    counterfactuals: list[c.Counterfactual] | None = None
    artefacts: list[c.Artefact] | None = None
    detail: dict[str, Any] = field(default_factory=dict)
    fidelity: float | None = None

    def top(self, n: int) -> list[c.Driver]:
        return sorted(self.drivers, key=lambda d: -abs(d.contribution))[:n]


type Runner = Callable[..., Result]


@dataclass(frozen=True)
class ExplainerSpec:
    """One registered explainer: `id` is `<method>@<version of the library or "own">`."""

    id: str
    method: str
    family: MethodFamily
    kinds: frozenset[str]
    run: Runner
    library: str | None = None
    note: str = ""

    @property
    def tag(self) -> str:
        return self.id


def direction(value: float) -> Literal["up", "down"]:
    return "up" if value >= 0 else "down"


def driver(feature: str, value: Any, contribution: float) -> c.Driver:
    if isinstance(value, np.generic):
        value = value.item()
    return c.Driver(feature=feature, value=value, contribution=float(contribution),
                    direction=direction(contribution))


def drivers_from(names: Iterable[str], values: Iterable[Any], contributions: Iterable[float]
                 ) -> list[c.Driver]:
    return [driver(n, v, k) for n, v, k in zip(names, values, contributions, strict=True)]


def to_explanation(result: Result, *, output_id: str, model_id: str, version: str,
                   text: str, explanation_id: str | None = None,
                   quality: c.ExplanationQuality | None = None,
                   causal_graph_ref: str | None = None) -> c.AHDTExplanation:
    return c.AHDTExplanation(
        explanation_id=explanation_id or f"exp-{uuid7()}", output_id=output_id,
        model_id=model_id, version=version, explainer=result.explainer,
        method_family=result.family, drivers=result.drivers, uncertainty=result.uncertainty,
        counterfactuals=result.counterfactuals, artefacts=result.artefacts, text=text,
        quality=quality, causal_graph_ref=causal_graph_ref)


def as_mapping(names: Sequence[str], x: Array) -> Mapping[str, float]:
    return {n: float(v) for n, v in zip(names, x, strict=True)}
