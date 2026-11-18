"""Layer 6.3 XAI services (design 04, 4.7.4): explain on demand, causal graph, automatic
explanation on decision thresholds and the explanation store.

An explanation is built from the stored output it explains: the model, its inputs and the
instance state it ran on. Its text is rendered for the audience and localised through the
language model chain, then checked by the output rail. Every explanation is stored with the
output id, the model version and the lake partition that holds the input snapshot.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, select

from ahdt.models.base import Layer4Base
from ahdt.models.reference import ReferenceStateModel
from ahdt.services import forecasting
from ahdt.services.model import Crossing, ModelService
from ahdt.services.outputs import StoredOutput
from ahdt.services.runtime import Runtime
from ahdt.xai.causal import ProvenanceRecorder
from ahdt.xai.explain import Explainer
from ahdt.xai.localise import Localiser
from ahdt.xai.probes import mechanistic_subject, reference_subject, rule_subject
from ahdt.xai.service import OutputRecord, XaiService
from ahdt.xai.subjects import WindowSubject
from atra import contracts as c
from atra.backends.base import RelationalBackend
from atra.service import Identity, Problem, ToolHandler, meta

log = logging.getLogger("ahdt.xai")
metadata = MetaData()
explanations = Table(
    "explanations", metadata,
    Column("explanation_id", String(64), primary_key=True),
    Column("output_id", String(64), nullable=False, index=True),
    Column("hdt_id", String(32), nullable=False, index=True),
    Column("model_id", String(160), nullable=False),
    Column("model_version", String(32), nullable=False),
    Column("audience", String(16), nullable=False),
    Column("language", String(8), nullable=False),
    Column("explainer", String(80), nullable=False),
    Column("inputs_ref", String(160), nullable=False),
    Column("trigger", String(32), nullable=False),
    Column("body", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

DETERIORATION_RISK = 0.3
RISK_KEYS = ("deterioration_risk",)
AUTO_AUDIENCE = "clinician"


@dataclass(frozen=True)
class StoredExplanation:
    explanation: c.AHDTExplanation
    language: str
    audience: str
    trigger: str


class ExplanationStore:
    """PostgreSQL (SQLite in p0) table `explanations`, linked to the output and its inputs."""

    def __init__(self, db: RelationalBackend) -> None:
        self.db = db
        self._ready = False

    async def _create(self) -> None:
        if not self._ready:
            async with self.db.engine().begin() as conn:
                await conn.run_sync(metadata.create_all)
            self._ready = True

    async def put(self, e: c.AHDTExplanation, *, hdt_id: str, audience: str, language: str,
                  inputs_ref: str, trigger: str) -> None:
        await self._create()
        async with self.db.engine().begin() as conn:
            await conn.execute(explanations.insert().values(
                explanation_id=e.explanation_id, output_id=e.output_id, hdt_id=hdt_id,
                model_id=e.model_id, model_version=e.version, audience=audience,
                language=language, explainer=e.explainer, inputs_ref=inputs_ref,
                trigger=trigger, body=json.loads(e.model_dump_json()),
                created_at=datetime.now(UTC)))

    async def find(self, output_id: str, audience: str, language: str
                   ) -> StoredExplanation | None:
        await self._create()
        async with self.db.engine().begin() as conn:
            row = (await conn.execute(select(explanations).where(
                explanations.c.output_id == output_id, explanations.c.audience == audience,
                explanations.c.language == language).order_by(
                    explanations.c.created_at.desc()))).first()
        return None if row is None else _stored(row)

    async def get(self, explanation_id: str) -> StoredExplanation | None:
        await self._create()
        async with self.db.engine().begin() as conn:
            row = (await conn.execute(select(explanations).where(
                explanations.c.explanation_id == explanation_id))).first()
        return None if row is None else _stored(row)

    async def for_output(self, output_id: str) -> list[StoredExplanation]:
        await self._create()
        async with self.db.engine().begin() as conn:
            rows = (await conn.execute(select(explanations).where(
                explanations.c.output_id == output_id))).all()
        return [_stored(r) for r in rows]


def _stored(row: Any) -> StoredExplanation:
    return StoredExplanation(c.AHDTExplanation.model_validate(row.body), row.language,
                             row.audience, row.trigger)


class XaiTools:
    def __init__(self, runtime: Runtime, models: ModelService, *,
                 localise_with_model: bool = True) -> None:
        self.rt = runtime
        self.store = ExplanationStore(runtime.backends.relational)
        self.explainer = Explainer()
        self.localise_with_model = localise_with_model
        self._service: XaiService | None = None
        self._explained: dict[tuple[str, str], tuple[str, str]] = {}
        models.on_output = self.on_output

    def language_of(self, hdt_id: str) -> str:
        return self.rt.languages.get(hdt_id, "en")

    # ---------------------------------------------------------------- subjects

    async def subject(self, record: OutputRecord) -> Any:
        found = (await self.rt.outputs()).get(record.output_id)
        if found is None:
            raise Problem(404, "not-found", f"no output {record.output_id}")
        return await asyncio.to_thread(self._subject, found)

    def _subject(self, out: StoredOutput) -> Any:
        if out.kind == "forecast":
            return self._window_subject(out)
        if out.kind not in ("state", "trajectory"):
            raise Problem(422, "not-explainable",
                          f"outputs of kind {out.kind} have no explainer")
        model = self.rt.catalogue.get(out.model_id)
        if model is None:
            raise Problem(422, "not-explainable", f"{out.model_id} has no explainer")
        instance = c.InstanceRecord(
            instance_id=f"inst-{out.hdt_id}-0", anatomy=model.spec.instances[0]
            if model.spec.instances else "", model_id=model.model_id, version=model.version,
            owner_dt=model.spec.twin, params=dict(out.params), state=dict(out.state))
        return _catalogue_subject(model, instance, out.inputs)

    @staticmethod
    def _window_subject(out: StoredOutput) -> WindowSubject:
        history = np.array([[float(p["v"])] for p in out.window])
        steps = int(out.values["steps"])
        return WindowSubject(
            model_id=out.model_id, version=out.version, columns=[str(out.values["variable"])],
            history=history, predict_batch=lambda ws: forecasting.predict_batch(ws, steps),
            horizon=steps, block=max(1, len(history) // 8))

    # ------------------------------------------------------------------ service

    async def service(self) -> XaiService:
        if self._service is None:
            pipe = await self.rt.pipeline()
            self._service = XaiService(self._lookup, self.subject, pipe.prov,
                                       language_of=self.language_of)
        return self._service

    async def _lookup(self, output_id: str) -> OutputRecord | None:
        return await (await self.rt.outputs()).lookup(output_id)

    def _localiser(self, language: str, loop: asyncio.AbstractEventLoop) -> Localiser:
        if not self.localise_with_model:
            return Localiser()

        def write(prompt: str) -> str:
            future = asyncio.run_coroutine_threadsafe(
                self.rt.converser.converse(prompt, locale=language, max_tokens=400), loop)
            return future.result(timeout=120).text

        return Localiser(write)

    async def build(self, out: StoredOutput, audience: str, language: str, trigger: str
                    ) -> c.AHDTExplanation:
        """Explain, render, localise and store the explanation of one output."""
        pipe = await self.rt.pipeline()
        cached = await self.store.find(out.output_id, audience, language)
        if cached is not None:
            return cached.explanation
        subject = await self.subject(out.record())
        loop = asyncio.get_running_loop()
        localiser = self._localiser(language, loop)

        def work() -> c.AHDTExplanation:
            done = self.explainer.explain(subject, output_id=out.output_id, audience=audience,
                                          causal_graph_ref=out.output_id)
            shown = localiser.render(done.explanation, audience, language,
                                     output=done.result.output)
            return done.explanation.model_copy(update={"text": shown.text})

        explanation = await asyncio.to_thread(work)
        weights = {out.sources[name]: d.contribution for d in explanation.drivers
                   if (name := d.feature.removeprefix("input:")) in out.sources}
        if weights:
            ProvenanceRecorder(pipe.prov).attributions(out.output_id, weights,
                                                       explanation.explainer)
        day = out.created_at.astimezone(UTC).date().isoformat()
        await self.store.put(explanation, hdt_id=out.hdt_id, audience=audience,
                             language=language, trigger=trigger,
                             inputs_ref=f"lake.outputs/ingested_day={day}/{out.output_id}")
        return explanation

    async def explain(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        out = (await self.rt.outputs()).get(a.output_id)
        if out is None or out.hdt_id != a.hdt_id:
            raise Problem(404, "not-found", f"no output {a.output_id} for this person")
        language = self.language_of(a.hdt_id)
        explanation = await self.build(out, a.audience, language, "request")
        body = explanation.model_dump(mode="json")
        body["_meta"] = meta((out.model_id, out.version), explainers=[explanation.explainer],
                             output_id=out.output_id)
        return body

    async def causal_graph(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        out = (await self.rt.outputs()).get(a.output_id)
        if out is None or out.hdt_id != a.hdt_id:
            raise Problem(404, "not-found", f"no output {a.output_id} for this person")
        return await (await self.service()).causal_graph(args, ident)

    # -------------------------------------------------------------- auto-explain

    def trigger_for(self, out: StoredOutput, info: Mapping[str, Any]) -> str | None:
        """Why an output should be explained without a request: anomaly severity at or
        above `watch`, a deterioration risk at or above 0.3, or a forecast that crosses a
        critical limit."""
        if info.get("status") in ("watch", "alert"):
            return f"severity:{info['status']}"
        crossing = info.get("crossing")
        if isinstance(crossing, Crossing):
            return f"forecast-crossing:{crossing.field}:{crossing.side}"
        for key in RISK_KEYS:
            value = out.values.get(key)
            if isinstance(value, int | float) and value >= DETERIORATION_RISK:
                return f"risk:{key}"
        return None

    async def on_output(self, out: StoredOutput, info: Mapping[str, Any]) -> None:
        trigger = self.trigger_for(out, info)
        if trigger is None or out.kind == "observed":
            return
        # An unchanged output with the same trigger was already explained; a read of the
        # same state does not build the explanation again.
        seen = (trigger, json.dumps(out.values, sort_keys=True, default=str))
        if self._explained.get((out.hdt_id, out.model_id)) == seen:
            return
        try:
            await self.build(out, AUTO_AUDIENCE, self.language_of(out.hdt_id), trigger)
            self._explained[(out.hdt_id, out.model_id)] = seen
        except Exception:
            log.warning("automatic explanation of %s failed", out.output_id, exc_info=True)

    def handlers(self) -> dict[str, ToolHandler]:
        return {"ahdt.xai.explain": self.explain, "ahdt.xai.causal_graph": self.causal_graph}


def _catalogue_subject(model: Layer4Base, record: c.InstanceRecord,
                       inputs: Mapping[str, Any]) -> Any:
    if isinstance(model, ReferenceStateModel):
        return reference_subject(model, record, inputs)
    if model.spec.family is c.ModelFamily.SEMANTIC:
        return rule_subject(model, inputs)
    return mechanistic_subject(model, record, inputs=inputs)
