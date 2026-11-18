"""The explain entry point: run a bound explainer on a subject and build the contract.

    Explainer().explain(subject, output_id=..., audience="clinician")

picks the default explainer of the subject's kind (or the one named), adds the
uncertainty block and the English text for the audience, and returns the
`AHDTExplanation` with the raw result.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from ahdt.xai.registry import ExplainerRegistry, default_registry
from ahdt.xai.render import PROFILES, render
from ahdt.xai.subjects import SignalSubject
from ahdt.xai.types import Result, Subject, to_explanation
from ahdt.xai.uncertainty import uncertainty_of
from atra import contracts as c


@dataclass
class Explained:
    explanation: c.AHDTExplanation
    result: Result
    kind: str


class Explainer:
    def __init__(self, registry: ExplainerRegistry | None = None) -> None:
        self.registry = registry or default_registry()

    def run(self, subject: Subject, explainer: str | None = None,
            options: Mapping[str, Any] | None = None) -> Result:
        spec = (self.registry.get(explainer) if explainer
                else next(x for x in self.registry.for_kind(subject.kind)
                          if self.registry.applies(x, subject)))
        if subject.kind not in spec.kinds:
            raise ValueError(f"{spec.id} does not explain a {subject.kind} model")
        return spec.run(subject, **(options or {}))

    def explain(self, subject: Subject, *, output_id: str, audience: str = "clinician",
                explainer: str | None = None, options: Mapping[str, Any] | None = None,
                causal_graph_ref: str | None = None) -> Explained:
        if audience not in PROFILES:
            raise ValueError(f"unknown audience {audience}")
        result = self.run(subject, explainer, options)
        result.uncertainty = {**uncertainty_of(subject, result), **result.uncertainty}
        label = (subject.classes[subject.target] if isinstance(subject, SignalSubject)
                 else None)
        draft = to_explanation(result, output_id=output_id, model_id=subject.model_id,
                               version=subject.version, text="",
                               causal_graph_ref=causal_graph_ref)
        text = render(draft, audience, output=result.output, kind=subject.kind, label=label)
        return Explained(draft.model_copy(update={"text": text}), result, subject.kind)
