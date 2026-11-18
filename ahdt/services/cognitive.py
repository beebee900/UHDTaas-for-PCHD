"""Layer 6.4 cognitive services (design 04, 4.7.5): converse, perceive, reason and
request_data.

- `converse` answers in en, yo, ha, ig or pcm through the language model chain, grounded on
  the person's latest readings, and keeps the session history.
- `perceive` turns text, speech and signals into findings. Quantities derived from a signal
  enter the ingest pipeline as `derived` observations.
- `reason` answers ontology, causal, probabilistic and temporal questions from the person's
  records and the shared ontologies.
- `request_data` queues a request for data, routes it to the person, device or clinician
  and tracks it until the data arrives or the deadline passes.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, MetaData, String, Table, select, update

from ahdt.knowledge.documents import PARTITION as FHIR_PARTITION
from ahdt.models.language.converse import Turn
from ahdt.services.runtime import Runtime
from ahdt.stores.waveforms import Segment
from atra import contracts as c
from atra.backends.base import WorkflowContext
from atra.codes import SYSTEMS
from atra.contracts import EventEnvelope
from atra.ids import new_record_id
from atra.service import Identity, Problem, ToolHandler, meta

SESSION_TTL_S = 24 * 3600
HISTORY_TURNS = 8
FACT_LIMIT = 8
RULE_CONFIDENCE = 1.0
UNCERTAIN_CONFIDENCE = 0.5
MIN_ECG_S = 5.0
DEFAULT_DEADLINE_H = 24.0
WORKFLOW = "data_request"

metadata = MetaData()
data_requests = Table(
    "data_requests", metadata,
    Column("request_id", String(64), primary_key=True),
    Column("hdt_id", String(32), nullable=False, index=True),
    Column("what", JSON, nullable=False),
    Column("source", String(16), nullable=False),
    Column("channel", String(8), nullable=False),
    Column("status", String(16), nullable=False),
    Column("deadline", DateTime(timezone=True), nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

def allen_relation(a: tuple[datetime, datetime], b: tuple[datetime, datetime]) -> str:
    """The Allen interval relation of `a` to `b`."""
    (a0, a1), (b0, b1) = a, b
    if a1 < b0:
        return "before"
    if a1 == b0:
        return "meets"
    if b1 < a0:
        return "after"
    if b1 == a0:
        return "met by"
    if a0 == b0 and a1 == b1:
        return "equals"
    if a0 == b0:
        return "starts" if a1 < b1 else "started by"
    if a1 == b1:
        return "finishes" if a0 > b0 else "finished by"
    if a0 > b0 and a1 < b1:
        return "during"
    if a0 < b0 and a1 > b1:
        return "contains"
    return "overlaps" if a0 < b0 else "overlapped by"


@dataclass(frozen=True)
class Episode:
    label: str
    start: datetime
    end: datetime


class CognitiveService:
    def __init__(self, runtime: Runtime, *, now: Any = None) -> None:
        self.rt = runtime
        self.now = now or (lambda: datetime.now(UTC))
        self._ready = False
        self._extractor: Any = None

    # ---------------------------------------------------------------- converse

    async def converse(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        rt = self.rt
        session = a.session_id or f"sess-{uuid.uuid4().hex}"
        cache = rt.backends.cache
        stored = await cache.get(f"ahdt:session:{a.hdt_id}:{session}") or []
        history = [Turn(t["role"], t["content"]) for t in stored][-HISTORY_TURNS:]
        facts, cites = await self._facts(a.hdt_id)
        reply = await rt.converser.converse(a.utterance, locale=a.language, history=history,
                                            facts=facts)
        rt.languages[a.hdt_id] = a.language
        turns = [*stored, {"role": "user", "content": a.utterance},
                 {"role": "assistant", "content": reply.text}]
        await cache.set(f"ahdt:session:{a.hdt_id}:{session}", turns[-2 * HISTORY_TURNS:],
                        ttl_s=SESSION_TTL_S)
        return {"reply": reply.text, "language": reply.locale, "session_id": session,
                "grounded_on": cites,
                "_meta": meta((f"language.{reply.backend}", reply.model))}

    async def _facts(self, hdt_id: str) -> tuple[list[str], list[dict[str, Any]]]:
        reader = await self.rt.reader()
        latest = sorted(reader.latest(hdt_id).values(), key=lambda r: r.effective_time,
                        reverse=True)[:FACT_LIMIT]
        facts, cites = [], []
        for r in latest:
            if r.value is None:
                continue
            name = reader.field_name(r.code) or r.code
            facts.append(f"{name} {r.value:g} {r.unit} on {r.effective_time:%Y-%m-%d %H:%M}"
                         if isinstance(r.value, float) else f"{name} {r.value}")
            cites.append({"node_id": r.record_id, "label": name})
        return facts, cites

    # ---------------------------------------------------------------- perceive

    async def perceive(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        if a.modality == "text":
            if not a.text:
                raise Problem(422, "invalid-arguments", "text modality needs `text`")
            return {"findings": await asyncio.to_thread(self._text_findings, a.text),
                    "transcript": a.text}
        if a.modality == "speech":
            return await self._speech(a)
        if a.modality == "signal":
            return await self._signal(a)
        raise Problem(501, "not-implemented",
                      "image perception needs the vision model, which this deployment lacks")

    def _text_findings(self, text: str) -> list[dict[str, Any]]:
        from ahdt.knowledge.extraction import NoteExtractor

        if self._extractor is None:
            self._extractor = NoteExtractor(self.rt.kb)
        found = self._extractor.extract(text)
        out = []
        for m in found.findings:
            if m.negated:
                continue
            entry = self.rt.kb.entry(m.ref).content()
            out.append({"code": str(entry.get("snomed") or m.ref),
                        "display": str(entry.get("name", m.text)),
                        "confidence": UNCERTAIN_CONFIDENCE if m.uncertain else RULE_CONFIDENCE})
        return out

    async def _speech(self, a: Any) -> Mapping[str, Any]:
        if not a.content_ref:
            raise Problem(422, "invalid-arguments", "speech modality needs `content_ref`")
        from ahdt.models.language.stt import SpeechToText

        pipe = await self.rt.pipeline()
        try:
            audio = await pipe.backends.objects.get(a.content_ref)
        except (KeyError, FileNotFoundError):
            raise Problem(404, "not-found", f"no audio at {a.content_ref}") from None
        stt = SpeechToText.from_dir(locale=a.language or "en")
        try:
            transcript = await stt.transcribe(audio, "audio/wav", a.language)
        except FileNotFoundError as exc:
            raise Problem(503, "unavailable", str(exc)) from exc
        return {"findings": await asyncio.to_thread(self._text_findings, transcript),
                "transcript": transcript}

    async def _signal(self, a: Any) -> Mapping[str, Any]:
        if not a.content_ref:
            raise Problem(422, "invalid-arguments", "signal modality needs `content_ref`")
        pipe = await self.rt.pipeline()
        segment = None
        for back in range(7):
            day = self.now() - timedelta(days=back)
            found = [s for s in pipe.waveforms.read(a.hdt_id, a.content_ref, day)
                     if len(s.samples) * s.period_ms / 1000.0 >= MIN_ECG_S]
            if found:
                segment = found[-1]
                break
        if segment is None:
            raise Problem(404, "not-found", f"no {a.content_ref} waveform of "
                                            f"{MIN_ECG_S:g} s or longer in the last 7 days")
        measures = await asyncio.to_thread(ecg_measures, segment)
        loinc = SYSTEMS["loinc"]
        findings = [
            {"code": "8867-4", "display": "Heart rate", "value": measures["heart_rate"],
             "confidence": measures["quality"]},
            {"code": "hrv_rmssd", "display": "Heart rate variability (RMSSD)",
             "value": measures["rmssd"], "confidence": measures["quality"]}]
        from ahdt.ingest.harmonise import RawObservation

        derived = RawObservation(
            record_id=new_record_id(), code=c.Code(system=loinc, code="8867-4"),
            value=measures["heart_rate"], unit="/min", effective_time=segment.start,
            source="derived", hdt_id=a.hdt_id)
        await pipe.process([derived])
        return {"findings": findings}

    # ------------------------------------------------------------------ reason

    async def reason(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        handler = {"ontology": self._ontology, "causal": self._causal,
                   "probabilistic": self._probabilistic, "temporal": self._temporal}[a.kind]
        answer, why = await handler(a.hdt_id, a.query)
        return {"answer": answer, "justification": why}

    async def _ontology(self, hdt_id: str, query: str) -> tuple[str, list[str]]:
        from ahdt.knowledge.ontology import STORE_DIR, Ontologies

        if not STORE_DIR.exists():
            raise Problem(503, "unavailable", "the ontology store is not built")
        m = re.fullmatch(r"\s*is\s+(.+?)\s+an?\s+(.+?)\s*\??\s*", query, re.IGNORECASE)
        if m is None:
            raise Problem(422, "invalid-arguments",
                          'ontology questions have the form "Is <term> a <term>?"')
        ontologies = Ontologies()
        terms = []
        for text in m.groups():
            term = _resolve_term(ontologies, text)
            if term is None:
                return "unknown", [f'"{text}" is not a term of the loaded ontologies']
            terms.append(term)
        child, parent = terms
        lines = [f"{child} ({ontologies.label(child)}) is_a* {parent} ({ontologies.label(parent)})"]
        if ontologies.is_a(child, parent):
            return "yes", lines
        return "no", [f"{child} has no is_a path to {parent}"]

    async def _causal(self, hdt_id: str, query: str) -> tuple[str, list[str]]:
        m = re.search(r"out-[0-9a-f-]+", query)
        if m is None:
            raise Problem(422, "invalid-arguments",
                          "causal questions name an output id, for example "
                          '"Why did out-... change?"')
        out = (await self.rt.outputs()).get(m.group(0))
        if out is None or out.hdt_id != hdt_id:
            raise Problem(404, "not-found", f"no output {m.group(0)} for this person")
        from ahdt.xai.causal import CausalGraphBuilder

        pipe = await self.rt.pipeline()
        graph = CausalGraphBuilder(pipe.prov).build(out.output_id)
        inputs = sorted(graph.inputs_of(graph.root), key=lambda e: -abs(e.weight))
        why = [f"{graph.nodes[e.source].label} contributed with weight {e.weight:.3g}"
               for e in inputs]
        return (f"{len(inputs)} inputs contributed to {graph.nodes[graph.root].label}",
                why or ["the output has no recorded inputs"])

    async def _probabilistic(self, hdt_id: str, query: str) -> tuple[str, list[str]]:
        m = re.fullmatch(
            r"\s*probability\s+(?:that\s+)?(\w+)\s+(?:is\s+)?(above|below)\s+(-?\d+(?:\.\d+)?)"
            r"\s+within\s+(\d+(?:\.\d+)?)\s*h(?:ours?)?\s*\??\s*", query, re.IGNORECASE)
        if m is None:
            raise Problem(422, "invalid-arguments",
                          'probabilistic questions have the form "Probability that <field> '
                          'is above <value> within <n> hours"')
        name, side, limit, hours = m.group(1), m.group(2).lower(), float(m.group(3)), \
            float(m.group(4))
        from ahdt.services import forecasting

        reader = await self.rt.reader()
        rows = [r for r in reader.read(hdt_id, [name]) if isinstance(r.value, float)]
        if len(rows) < forecasting.MIN_POINTS:
            raise Problem(409, "insufficient-data",
                          f"{name} has {len(rows)} readings; at least "
                          f"{forecasting.MIN_POINTS} are needed")
        t0 = rows[0].effective_time
        grid, step = forecasting.regular_grid(
            [(r.effective_time - t0).total_seconds() / 3600 for r in rows],
            [float(r.value) for r in rows])  # type: ignore[arg-type]
        steps = forecasting.ahead(hours, step)
        mean, half = forecasting.forecast(forecasting.fit(grid), steps)
        z = 1.6448536269514722
        sigma = np.maximum(half / z, 1e-9)
        from scipy.stats import norm

        p = norm.sf((limit - mean) / sigma) if side == "above" else norm.cdf(
            (limit - mean) / sigma)
        worst = float(np.max(p))
        return (f"{worst:.3f}",
                [f"damped-trend forecast of {name} over {steps} steps of {step:.3g} h",
                 "Gaussian band from the 90 % half-width",
                 f"largest probability over the horizon of being {side} {limit:g}"])

    async def _temporal(self, hdt_id: str, query: str) -> tuple[str, list[str]]:
        m = re.fullmatch(r"\s*(?:relation|how)\b.*?\bbetween\s+(.+?)\s+and\s+(.+?)\s*\??\s*",
                         query, re.IGNORECASE)
        if m is None:
            raise Problem(422, "invalid-arguments",
                          'temporal questions have the form "Relation between <A> and <B>"')
        episodes = await self._episodes(hdt_id)
        found = []
        for text in m.groups():
            hit = next((e for e in episodes if text.lower() in e.label.lower()), None)
            if hit is None:
                return "unknown", [f'no recorded episode matches "{text}"']
            found.append(hit)
        first, second = found
        relation = allen_relation((first.start, first.end), (second.start, second.end))
        return relation, [f"{first.label}: {first.start:%Y-%m-%d} to {first.end:%Y-%m-%d}",
                          f"{second.label}: {second.start:%Y-%m-%d} to {second.end:%Y-%m-%d}"]

    async def _episodes(self, hdt_id: str) -> list[Episode]:
        pipe = await self.rt.pipeline()
        fhir = pipe.backends.fhir
        subject = {"subject": f"Patient/{hdt_id}"}
        out = []
        for r in await fhir.search("MedicationStatement", subject, partition=FHIR_PARTITION):
            period = r.get("effectivePeriod") or {}
            if period.get("start"):
                out.append(_episode(_label(r.get("medicationCodeableConcept")),
                                    period["start"], period.get("end")))
        for r in await fhir.search("Condition", subject, partition=FHIR_PARTITION):
            start = r.get("onsetDateTime")
            if start:
                out.append(_episode(_label(r.get("code")), start, r.get("abatementDateTime")))
        return out

    # ------------------------------------------------------------ request_data

    async def _setup(self) -> None:
        if self._ready:
            return
        async with self.rt.backends.relational.engine().begin() as conn:
            await conn.run_sync(metadata.create_all)
        workflows = self.rt.backends.workflows
        workflows.register(WORKFLOW, self._workflow)
        self.rt.backends.events.subscribe("observation.ingested", self._arrived)
        self._ready = True

    async def _workflow(self, ctx: WorkflowContext, request_id: str, hdt_id: str,
                        channel: str, source: str, what: list[str], deadline_h: float) -> str:
        sent = await ctx.activity(self._send, request_id, hdt_id, channel, source, what)
        if sent != "sent":
            return str(sent)
        answer = await ctx.wait_signal("answered", timeout_s=deadline_h * 3600.0)
        status = "answered" if answer is not None else "expired"
        await ctx.activity(self._finish, request_id, status)
        return status

    async def _send(self, request_id: str, hdt_id: str, channel: str, source: str,
                    what: list[str]) -> str:
        used = await self.rt.notifier.send(hdt_id, source, channel=channel,  # type: ignore[arg-type]
                                           request_id=request_id, what=what)
        status = "sent" if used else "expired"
        await self._set_status(request_id, status)
        return status

    async def _finish(self, request_id: str, status: str) -> str:
        await self._set_status(request_id, status)
        return status

    async def _set_status(self, request_id: str, status: str) -> None:
        async with self.rt.backends.relational.engine().begin() as conn:
            await conn.execute(update(data_requests).where(
                data_requests.c.request_id == request_id).values(status=status))

    async def _arrived(self, event: EventEnvelope) -> None:
        """Data for an open request has arrived: answer the request."""
        async with self.rt.backends.relational.engine().begin() as conn:
            rows = (await conn.execute(select(data_requests).where(
                data_requests.c.hdt_id == event.hdt_id,
                data_requests.c.status.in_(("queued", "sent"))))).all()
        reader = await self.rt.reader()
        code = reader.canonical(str(event.payload["code"]))
        for row in rows:
            if code in {reader.canonical(w) for w in row.what}:
                await self.rt.backends.workflows.signal(row.request_id, "answered", True)

    async def request_data(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        await self._setup()
        deadline_h = a.deadline_h or DEFAULT_DEADLINE_H
        channel = a.channel or "app"
        request_id = f"req-{uuid.uuid4().hex}"
        now = self.now()
        async with self.rt.backends.relational.engine().begin() as conn:
            await conn.execute(data_requests.insert().values(
                request_id=request_id, hdt_id=a.hdt_id, what=list(a.what), source=a.from_,
                channel=channel, status="queued", deadline=now + timedelta(hours=deadline_h),
                created_at=now))
        await self.rt.backends.workflows.start(
            WORKFLOW, {"request_id": request_id, "hdt_id": a.hdt_id, "channel": channel,
                       "source": a.from_, "what": list(a.what), "deadline_h": deadline_h},
            run_id=request_id)
        return {"request_id": request_id, "status": "queued"}

    def handlers(self) -> dict[str, ToolHandler]:
        return {"ahdt.cognitive.converse": self.converse,
                "ahdt.cognitive.perceive": self.perceive, "ahdt.cognitive.reason": self.reason,
                "ahdt.cognitive.request_data": self.request_data}


def ecg_measures(segment: Segment) -> dict[str, float]:
    """Heart rate, RMSSD and a signal-quality score (0 to 1) of an ECG segment."""
    import neurokit2 as nk

    fs = 1000.0 / segment.period_ms
    rate = round(fs)
    cleaned = nk.ecg_clean(segment.samples, sampling_rate=rate)
    _, info = nk.ecg_peaks(cleaned, sampling_rate=rate)
    peaks = np.asarray(info["ECG_R_Peaks"])
    if len(peaks) < 3:
        raise Problem(422, "unusable-signal", "the ECG segment has fewer than three beats")
    rr_ms = np.diff(peaks) / fs * 1000.0
    quality = nk.ecg_quality(cleaned, rpeaks=peaks, sampling_rate=rate)
    return {"heart_rate": float(60000.0 / rr_ms.mean()),
            "rmssd": float(np.sqrt(np.mean(np.diff(rr_ms) ** 2))),
            "quality": float(np.clip(np.mean(quality), 0.0, 1.0))}


def _resolve_term(ontologies: Any, text: str) -> str | None:
    if re.fullmatch(r"[A-Za-z]+:\d+", text):
        return text if ontologies.exists(text) else None
    literal = text.replace("\\", "\\\\").replace('"', '\\"').lower()
    rows = ontologies.store.query(
        "SELECT ?t WHERE { ?t <http://www.w3.org/2000/01/rdf-schema#label> ?l "
        f'FILTER(LCASE(STR(?l)) = "{literal}") }} LIMIT 1', use_default_graph_as_union=True)
    from ahdt.knowledge.ontology import curie

    for row in rows:
        return curie(str(row["t"].value))
    return None


def _label(concept: Mapping[str, Any] | None) -> str:
    if not concept:
        return "unknown"
    if concept.get("text"):
        return str(concept["text"])
    for coding in concept.get("coding", []):
        if coding.get("display"):
            return str(coding["display"])
    return str((concept.get("coding") or [{}])[0].get("code", "unknown"))


def _episode(label: str, start: str, end: str | None) -> Episode:
    def when(value: str) -> datetime:
        t = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return t if t.tzinfo else t.replace(tzinfo=UTC)

    s = when(start)
    return Episode(label, s, when(end) if end else datetime.now(UTC))

