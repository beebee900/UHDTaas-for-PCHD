"""Handlers of the `ahdt.xai.explain` and `ahdt.xai.causal_graph` tools (design 03, 3.5).

`XaiService.handlers()` returns handlers for `atra.service.ToolExecutor`. The service
finds the model output, asks the subject provider for the model and the instance behind
it, runs the bound explainer, renders and localises the text, and attaches the causal
graph reference. Where outputs are stored and how subjects are built (lake rows, model
artifacts) belongs to the model service that owns the output.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel

from ahdt.xai.causal import CausalGraphBuilder
from ahdt.xai.explain import Explainer
from ahdt.xai.localise import Localiser
from ahdt.xai.registry import ExplainerRegistry
from ahdt.xai.types import Subject
from atra import contracts as c
from atra.provenance import ProvenanceStore
from atra.service import Identity, ToolHandler, meta


@dataclass(frozen=True)
class OutputRecord:
    """A model output as the model service stored it."""

    output_id: str
    model_id: str
    version: str
    hdt_id: str
    inputs: Mapping[str, Any] = field(default_factory=dict)


class UnknownOutput(LookupError):
    pass


type OutputLookup = Callable[[str], Awaitable[OutputRecord | None]]
type SubjectProvider = Callable[[OutputRecord], Awaitable[Subject]]
type LanguageOf = Callable[[str], str]


class XaiService:
    def __init__(self, outputs: OutputLookup, subjects: SubjectProvider,
                 provenance: ProvenanceStore, *, registry: ExplainerRegistry | None = None,
                 localiser: Localiser | None = None,
                 language_of: LanguageOf | None = None) -> None:
        self.outputs = outputs
        self.subjects = subjects
        self.provenance = provenance
        self.explainer = Explainer(registry)
        self.localiser = localiser or Localiser()
        self.language_of = language_of or (lambda hdt_id: "en")

    async def _record(self, output_id: str, hdt_id: str) -> OutputRecord:
        record = await self.outputs(output_id)
        if record is None or record.hdt_id != hdt_id:
            raise UnknownOutput(output_id)
        return record

    async def explain(self, args: BaseModel, ident: Identity) -> dict[str, Any]:
        a = _args(args)
        record = await self._record(a.output_id, a.hdt_id)
        subject = await self.subjects(record)
        done = self.explainer.explain(subject, output_id=record.output_id, audience=a.audience,
                                      causal_graph_ref=record.output_id)
        language = self.language_of(record.hdt_id)
        shown = self.localiser.render(done.explanation, a.audience, language,
                                      output=done.result.output)
        body = done.explanation.model_copy(update={"text": shown.text})
        out = body.model_dump(mode="json")
        out["_meta"] = meta((record.model_id, record.version),
                            explainers=[done.explanation.explainer],
                            output_id=record.output_id)
        return out

    async def causal_graph(self, args: BaseModel, ident: Identity) -> dict[str, Any]:
        a = _args(args)
        await self._record(a.output_id, a.hdt_id)
        graph = CausalGraphBuilder(self.provenance).build(a.output_id)
        return graph.to_contract().model_dump(mode="json", by_alias=True)

    def handlers(self) -> dict[str, ToolHandler]:
        return {"ahdt.xai.explain": self.explain, "ahdt.xai.causal_graph": self.causal_graph}


def _args(args: BaseModel) -> Any:
    if not isinstance(args, c.ExplainArgs | c.CausalGraphArgs):
        raise TypeError(type(args).__name__)
    return args
