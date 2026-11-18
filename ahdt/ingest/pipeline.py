"""The AHDT Layer 3.1 ingestion pipeline: receive, validate, harmonise, pseudonymise with
consent and provenance, route (design 04, 4.3.1).

Every record ends in exactly one outcome: accepted, duplicate, rejected (kept in
`ingest_rejected` with its reason) or dropped for missing consent (audited). Accepted
records are written to the time-series store, to FHIR when the field is not a high-rate
stream, to the waveform store for arrays, and to `lake.observations`; each publishes
`observation.ingested`.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, TypeGuard

from sqlalchemy import select

from ahdt.ingest.fields import FieldIndex, field_index
from ahdt.ingest.harmonise import (
    Harmonised,
    HarmoniseError,
    RawObservation,
    fhir_observation,
    harmonise,
)
from ahdt.ingest.privacy import Pseudonymiser, consent_tag
from ahdt.ingest.validate import Row, cross_field, rate_limit, validate
from ahdt.stores import tables
from ahdt.stores.lake import Lake
from ahdt.stores.waveforms import WaveformStore
from atra.backends import Backends
from atra.backends.base import TSPoint
from atra.consent import ConsentRegistry
from atra.contracts import Code, EventEnvelope, ObservationRecord, Quality, Waveform
from atra.ids import new_record_id
from atra.provenance import AuditLog, ProvenanceStore

FHIR_PARTITION = "ahdt"
SERVICE_ACTOR = {"id": "ahdt-ingest", "role": "service"}


@dataclass
class Rejection:
    record_id: str
    reason: str
    stage: str


@dataclass
class IngestResult:
    accepted: list[ObservationRecord] = field(default_factory=list)
    duplicates: list[str] = field(default_factory=list)
    rejected: list[Rejection] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return {"accepted": len(self.accepted), "duplicates": len(self.duplicates),
                "rejected": len(self.rejected), "dropped": len(self.dropped)}


@dataclass
class _Pending:
    h: Harmonised
    hdt_id: str
    key: str


def _scalar(v: object) -> TypeGuard[int | float]:
    return isinstance(v, int | float) and not isinstance(v, bool)


class IngestPipeline:
    def __init__(self, backends: Backends, consents: ConsentRegistry, audit: AuditLog, *,
                 lake: Lake, waveforms: WaveformStore, hdt_key: bytes,
                 index: FieldIndex | None = None) -> None:
        self.backends = backends
        self.consents = consents
        self.audit = audit
        self.lake = lake
        self.waveforms = waveforms
        self.index = index or field_index()
        self.pseudonyms = Pseudonymiser(backends.relational, hdt_key)
        self.prov = ProvenanceStore("ahdt")
        self._ready = False

    async def start(self) -> None:
        if not self._ready:
            await tables.create_all(self.backends.relational)
            self._ready = True

    def subscribe(self) -> None:
        """Consume `ingest.<twin>` events from the bus (the p0 stand-in for Kafka topics)."""
        async def handle(event: EventEnvelope) -> None:
            await self.process(raw_from_payload(o) for o in event.payload["observations"])

        self.backends.events.subscribe("ingest.*", handle)

    async def process(self, raws: Iterable[RawObservation]) -> IngestResult:
        await self.start()
        result = IngestResult()
        pending: list[_Pending] = []
        batch_keys: set[str] = set()
        for raw in raws:
            key = f"{raw.idempotency_key or raw.record_id}@{raw.version}"
            if key in batch_keys or await self._seen(key):
                result.duplicates.append(raw.record_id)
                continue
            batch_keys.add(key)
            try:
                hdt_id = await self._subject(raw)
                h = harmonise(raw, self.index)
            except HarmoniseError as exc:
                await self._reject(result, raw, None, str(exc), "harmonise")
                continue
            pending.append(_Pending(h, hdt_id, key))
        pending = await self._validate(result, pending)
        pending = await self._rates(result, pending)
        stored: list[tuple[_Pending, ObservationRecord]] = []
        for p in pending:
            tag = consent_tag(self.consents.get(p.hdt_id))
            if tag is None:
                result.dropped.append(p.h.raw.record_id)
                self.audit.append(actor=SERVICE_ACTOR, action="ingest.drop",
                                  target=p.h.raw.record_id, purpose="care", outcome="denied",
                                  hdt_id=p.hdt_id, reason="no consent for care")
                continue
            stored.append((p, await self._store(p, tag)))
        # One lake snapshot per batch; a key is marked seen only after its lake row is written.
        now = datetime.now(UTC)
        self.lake.append("observations", [_lake_row(record, now) for _, record in stored])
        for p, record in stored:
            await self._commit(p, record, now)
            result.accepted.append(record)
        return result

    async def _subject(self, raw: RawObservation) -> str:
        if raw.hdt_id:
            return raw.hdt_id
        if raw.identifier:
            return await self.pseudonyms.hdt_id(*raw.identifier)
        raise HarmoniseError("the record names no subject")

    async def _seen(self, key: str) -> bool:
        async with self.backends.relational.engine().begin() as conn:
            row = (await conn.execute(select(tables.seen.c.key).where(
                tables.seen.c.key == key))).first()
        return row is not None

    async def _reject(self, result: IngestResult, raw: RawObservation, hdt_id: str | None,
                      reason: str, stage: str) -> None:
        result.rejected.append(Rejection(raw.record_id, reason, stage))
        value = raw.value.model_dump() if isinstance(raw.value, Waveform) else raw.value
        async with self.backends.relational.engine().begin() as conn:
            await conn.execute(tables.rejected.insert().values(
                record_id=raw.record_id, hdt_id=hdt_id or raw.hdt_id,
                code=f"{raw.code.system}|{raw.code.code}", value=value, unit=raw.unit,
                effective_time=raw.effective_time, reason=reason, stage=stage,
                received_at=datetime.now(UTC)))

    async def _validate(self, result: IngestResult, pending: list[_Pending]) -> list[_Pending]:
        by_twin: dict[Any, list[int]] = defaultdict(list)
        for i, p in enumerate(pending):
            by_twin[p.h.ref.twin].append(i)
        bad: dict[int, str] = {}
        for twin, positions in by_twin.items():
            rows = [Row(pending[i].h.ref.field.name, pending[i].h.value, pending[i].h.unit)
                    for i in positions]
            for pos, reason in validate(twin, rows).items():
                bad[positions[pos]] = reason
        groups: dict[tuple[str, datetime], dict[str, tuple[int, float]]] = defaultdict(dict)
        for i, p in enumerate(pending):
            v = p.h.value
            if i not in bad and _scalar(v):
                groups[(p.hdt_id, p.h.raw.effective_time)][p.h.ref.field.name] = (i, float(v))
        for group in groups.values():
            members = {name: i for name, (i, _) in group.items()}
            values = {name: v for name, (_, v) in group.items()}
            for rule_id, fields in cross_field(values):
                for name in fields:
                    bad.setdefault(members[name], f"fails consistency rule {rule_id}")
        for i, reason in sorted(bad.items()):
            await self._reject(result, pending[i].h.raw, pending[i].hdt_id, reason, "validate")
        return [p for i, p in enumerate(pending) if i not in bad]

    async def _rates(self, result: IngestResult, pending: list[_Pending]) -> list[_Pending]:
        """Rate-of-change rules against the latest stored value of the same field."""
        keep = []
        for p in pending:
            limit = rate_limit(p.h.ref.field.name)
            if limit is None or not _scalar(p.h.value):
                keep.append(p)
                continue
            rule_id, max_change, period_h = limit
            last = await self.backends.timeseries.latest(p.hdt_id, p.h.ref.code.code)
            if last is not None and _scalar(last.v):
                hours = abs((p.h.raw.effective_time - last.t).total_seconds()) / 3600.0
                allowed = max_change * max(hours / period_h, 1.0)
                if abs(float(p.h.value) - float(last.v)) > allowed:
                    await self._reject(result, p.h.raw, p.hdt_id,
                                       f"fails rate rule {rule_id}", "validate")
                    continue
            keep.append(p)
        return keep

    async def _store(self, p: _Pending, tag: str) -> ObservationRecord:
        h, raw = p.h, p.h.raw
        entity = self.prov.entity(raw.record_id, "observation", hdt_id=p.hdt_id,
                                  code=h.ref.code.code)
        if raw.device_id:
            device = self.prov.agent(raw.device_id, "device")
            self.prov.activity("ingest", generated=[raw.record_id], agent=device)
        else:
            self.prov.activity("ingest", generated=[raw.record_id])
        record = ObservationRecord(
            record_id=raw.record_id, hdt_id=p.hdt_id, dt=h.ref.twin, code=h.ref.code,
            alt_codes=h.ref.alt_codes, value=h.value, unit=h.unit,
            effective_time=raw.effective_time, sim_time=raw.sim_time, device_id=raw.device_id,
            source=_source(raw.source), quality=Quality.OK, consent_tag=tag,
            provenance_id=entity, version=raw.version)
        code = h.ref.code.code
        if isinstance(h.value, Waveform):
            self.waveforms.append(p.hdt_id, code, raw.effective_time, h.value.array,
                                  h.value.period_ms)
        else:
            await self.backends.timeseries.write(p.hdt_id, code, [
                TSPoint(raw.effective_time, h.value, h.unit, "ok", raw.version)])
            if h.ref.field.sample_period_s is None:
                resource = fhir_observation(h, hdt_id=p.hdt_id, record_id=raw.record_id,
                                            consent_tag=tag)
                write = self.backends.fhir.create if raw.version == 1 else self.backends.fhir.update
                await write(resource, partition=FHIR_PARTITION)
        return record

    async def _commit(self, p: _Pending, record: ObservationRecord, now: datetime) -> None:
        h, raw = p.h, p.h.raw
        async with self.backends.relational.engine().begin() as conn:
            await conn.execute(tables.seen.insert().values(
                key=p.key, record_id=raw.record_id, version=raw.version))
        await self.backends.events.publish(EventEnvelope(
            event_id=new_record_id(), event_type="observation.ingested", source="ahdt.ingest",
            hdt_id=p.hdt_id, wall_time=now, sim_time=raw.sim_time, trace_id=new_record_id(),
            payload={"record_id": raw.record_id, "dt": h.ref.twin.value,
                     "code": h.ref.code.code, "field": h.ref.field.name,
                     "effective_time": raw.effective_time.isoformat(),
                     "value": None if isinstance(h.value, Waveform) else h.value,
                     "unit": h.unit, "provenance_id": record.provenance_id}))


_SOURCES = {"device", "manual", "self_report", "derived", "import"}


def _source(value: str) -> Any:
    return value if value in _SOURCES else "device"


def _lake_row(r: ObservationRecord, ingested_at: datetime) -> dict[str, Any]:
    v = r.value
    numeric = _scalar(v)
    text = None if numeric or isinstance(v, Waveform) else str(v).lower() if isinstance(
        v, bool) else str(v)
    return {"record_id": r.record_id, "hdt_id": r.hdt_id, "dt": r.dt.value,
            "code_system": r.code.system, "code": r.code.code,
            "value_num": float(v) if _scalar(v) else None, "value_text": text, "unit": r.unit,
            "effective_time": r.effective_time, "ingested_at": ingested_at,
            "source": r.source, "quality": r.quality.value, "consent_tag": r.consent_tag,
            "provenance_id": r.provenance_id, "version": r.version, "device_id": r.device_id}


def raw_from_payload(o: Mapping[str, Any]) -> RawObservation:
    """A `RawObservation` from the JSON form used on `ingest.<twin>` topics and batch CSV."""
    value = o["value"]
    if isinstance(value, Mapping):
        value = Waveform.model_validate(value)
    ident = o.get("identifier")
    return RawObservation(
        record_id=str(o.get("record_id") or new_record_id()),
        code=Code.model_validate(o["code"]), value=value, unit=str(o.get("unit", "1")),
        effective_time=datetime.fromisoformat(str(o["effective_time"])),
        source=str(o.get("source", "device")), hdt_id=o.get("hdt_id"),
        identifier=(str(ident["system"]), str(ident["value"])) if ident else None,
        alt_codes=[Code.model_validate(c) for c in o.get("alt_codes", [])],
        device_id=o.get("device_id"), sim_time=o.get("sim_time"),
        version=int(o.get("version", 1)), idempotency_key=o.get("idempotency_key"))

