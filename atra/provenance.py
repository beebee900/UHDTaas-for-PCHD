"""W3C PROV records and the hash-chained audit log (design 03, section 3.11)."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Iterable, Iterator, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import prov.model as pm

from atra.contracts import Actor, AuditRecord
from atra.ids import uuid7

GENESIS_HASH = "0" * 64
PROV_NS = "https://atra.local/prov#"

type EntityKind = Literal["observation", "model_output", "explanation", "message", "document"]
type ActivityKind = Literal["ingest", "predict", "simulate", "explain", "transfer", "decide"]
type AgentKind = Literal["device", "service", "ai_agent", "human"]


def canonical_json(obj: Mapping[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=_json_default,
                      ensure_ascii=False).encode()


def _json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    raise TypeError(f"not JSON serialisable: {type(value).__name__}")


def record_hash(record: Mapping[str, Any]) -> str:
    """SHA-256 over the canonical JSON of the record without its `hash` field."""
    body = {k: v for k, v in record.items() if k != "hash"}
    return hashlib.sha256(canonical_json(body)).hexdigest()


class ChainBroken(ValueError):
    """`verify_chain` found a record whose hash or link does not match."""


class AuditLog:
    """Append-only, hash-chained audit log of one service.

    Records are kept in memory and, when `path` is given, appended to a JSON-lines file
    that is re-read on start, so the chain continues across restarts.
    """

    def __init__(self, service: str, *, path: Path | None = None) -> None:
        self.service = service
        self.path = path
        self._records: list[AuditRecord] = []
        self._lock = threading.Lock()
        if path is not None and path.exists():
            with path.open(encoding="utf-8") as fh:
                self._records = [AuditRecord.model_validate_json(line)
                                 for line in fh if line.strip()]

    def append(self, *, actor: Actor | Mapping[str, str], action: str, target: str,
               purpose: str, outcome: Literal["ok", "denied", "degraded", "error"],
               trace_id: str | None = None, t: datetime | None = None,
               **optional: Any) -> AuditRecord:
        with self._lock:
            prev = self._records[-1] if self._records else None
            body: dict[str, Any] = {
                "seq": 0 if prev is None else prev.seq + 1,
                "prev_hash": GENESIS_HASH if prev is None else prev.hash,
                "t": (t or datetime.now(UTC)).isoformat(),
                "service": self.service,
                "actor": dict(actor) if isinstance(actor, Mapping) else actor.model_dump(),
                "action": action, "target": target, "purpose": purpose, "outcome": outcome,
                "trace_id": trace_id or uuid7().hex,
                **{k: v for k, v in optional.items() if v is not None},
            }
            record = AuditRecord.model_validate({**body, "hash": ""})
            dumped = record.model_dump(mode="json", exclude_none=True)
            record = record.model_copy(update={"hash": record_hash(dumped)})
            self._records.append(record)
            if self.path is not None:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(record.model_dump_json(exclude_none=True) + "\n")
            return record

    def __iter__(self) -> Iterator[AuditRecord]:
        return iter(list(self._records))

    def __len__(self) -> int:
        return len(self._records)

    def query(self, **match: Any) -> list[AuditRecord]:
        return [r for r in self._records
                if all(getattr(r, k, None) == v for k, v in match.items())]

    def verify_chain(self) -> int:
        """Recompute every hash and link. Returns the number of records checked."""
        return verify_chain(self._records)


def verify_chain(records: Iterable[AuditRecord]) -> int:
    prev_hash, count = GENESIS_HASH, 0
    for expected_seq, rec in enumerate(records):
        dumped = rec.model_dump(mode="json", exclude_none=True)
        if rec.seq != expected_seq:
            raise ChainBroken(f"record {rec.seq}: expected seq {expected_seq}")
        if rec.prev_hash != prev_hash:
            raise ChainBroken(f"record {rec.seq}: link to the previous record is broken")
        if record_hash(dumped) != rec.hash:
            raise ChainBroken(f"record {rec.seq}: content does not match its hash")
        prev_hash, count = rec.hash, count + 1
    return count


class ProvenanceStore:
    """W3C PROV-O document for one service, with string identifiers usable in messages."""

    def __init__(self, service: str) -> None:
        self.service = service
        self.doc = pm.ProvDocument()
        self.doc.add_namespace("atra", PROV_NS)
        self._lock = threading.Lock()
        self._service_agent = self.agent(f"svc-{service}", "service")

    @staticmethod
    def _qn(local: str) -> str:
        return local if local.startswith("atra:") else f"atra:{local}"

    def entity(self, local_id: str, kind: EntityKind, **attrs: Any) -> str:
        qn = self._qn(local_id)
        with self._lock:
            self.doc.entity(qn, {"atra:kind": kind, **_attrs(attrs)})
        return qn

    def activity(self, kind: ActivityKind, *, used: Iterable[str] = (),
                 generated: Iterable[str] = (), agent: str | None = None,
                 **attrs: Any) -> str:
        qn = self._qn(f"{kind}-{uuid7().hex}")
        now = datetime.now(UTC)
        with self._lock:
            act = self.doc.activity(qn, now, now, {"atra:kind": kind, **_attrs(attrs)})
            for e in used:
                self.doc.used(act, self._qn(e))
            for e in generated:
                self.doc.wasGeneratedBy(self._qn(e), act)
            self.doc.wasAssociatedWith(act, agent or self._service_agent)
        return qn

    def agent(self, local_id: str, kind: AgentKind, **attrs: Any) -> str:
        qn = self._qn(local_id)
        with self._lock:
            self.doc.agent(qn, {"atra:kind": kind, **_attrs(attrs)})
        return qn

    def derived(self, generated: str, used: str) -> None:
        with self._lock:
            self.doc.wasDerivedFrom(self._qn(generated), self._qn(used))

    def lineage(self, entity: str) -> list[str]:
        """Entities that `entity` was derived from or whose activity generated it, transitively."""
        graph: dict[str, set[str]] = {}
        act_inputs: dict[str, set[str]] = {}
        for rec in self.doc.get_records():
            attrs = {str(k): str(v) for k, v in rec.formal_attributes if v is not None}
            if isinstance(rec, pm.ProvDerivation):
                graph.setdefault(attrs["prov:generatedEntity"], set()).add(attrs["prov:usedEntity"])
            elif isinstance(rec, pm.ProvUsage):
                act_inputs.setdefault(attrs["prov:activity"], set()).add(attrs["prov:entity"])
        for rec in self.doc.get_records(pm.ProvGeneration):
            attrs = {str(k): str(v) for k, v in rec.formal_attributes if v is not None}
            graph.setdefault(attrs["prov:entity"], set()).update(
                act_inputs.get(attrs.get("prov:activity", ""), set()))
        seen: list[str] = []
        stack = [self._qn(entity)]
        while stack:
            for parent in sorted(graph.get(stack.pop(), ())):
                if parent not in seen:
                    seen.append(parent)
                    stack.append(parent)
        return seen

    def serialize(self) -> str:
        with self._lock:
            return str(self.doc.serialize(format="json"))


def _attrs(attrs: Mapping[str, Any]) -> dict[str | pm.Identifier, Any]:
    return {f"atra:{k}": v if isinstance(v, str | int | float | bool)
            else json.dumps(v, default=str) for k, v in attrs.items()}
