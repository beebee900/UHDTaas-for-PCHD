"""Store-and-forward from the edge to the AHDT (design 04, 4.2.2; NFR6).

Every reading that leaves the edge is first written to a SQLite outbox: `seq`, an idempotency
key, the zstd-compressed JSON payload and a status. The forwarder sends pending rows in `seq`
order to the AHDT gRPC `ObservationService.Ingest` and marks them acknowledged when the
`IngestAck` arrives. A row whose send fails stays pending and is sent again after the link
returns.

The idempotency key is a hash of the reading itself (person, device, code, time, value). A
reading that arrives twice at the edge, for example an MQTT QoS 1 redelivery, is stored once.
A batch sent again because its acknowledgement was lost is counted by the AHDT as duplicates,
because the AHDT stores each idempotency key once.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

import zstandard

from atra.ids import new_record_id

PENDING, ACKED, REJECTED = "pending", "acked", "rejected"
_SCHEMA = """CREATE TABLE IF NOT EXISTS outbox (
    seq INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL UNIQUE, record_id TEXT NOT NULL,
    hdt_id TEXT NOT NULL, payload BLOB NOT NULL, status TEXT NOT NULL,
    attempts INTEGER NOT NULL DEFAULT 0, enqueued_at TEXT NOT NULL, acked_at TEXT)"""
_INDEX = "CREATE INDEX IF NOT EXISTS outbox_status ON outbox (status, seq)"


def idempotency_key(p: Mapping[str, Any]) -> str:
    identity = [p.get("hdt_id"), p.get("device_id"), p["code"]["system"], p["code"]["code"],
                p["effective_time"], p["value"], p.get("unit"), p.get("source")]
    blob = json.dumps(identity, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


@dataclass(frozen=True)
class Row:
    seq: int
    key: str
    record_id: str
    payload: dict[str, Any]

    def observation(self) -> dict[str, Any]:
        return {**self.payload, "record_id": self.record_id, "idempotency_key": self.key}


@dataclass(frozen=True)
class Ack:
    accepted: int
    duplicates: int
    rejected: int
    rejected_ids: tuple[str, ...] = ()


class LinkDown(ConnectionError):
    """The AHDT cannot be reached; the batch stays pending."""


class Ingestor(Protocol):
    async def ingest(self, observations: Sequence[Mapping[str, Any]]) -> Ack: ...


class Outbox:
    def __init__(self, path: Path | None = None, *,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.clock = clock
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL" if path else "PRAGMA journal_mode=MEMORY")
        self._db.execute(_SCHEMA)
        self._db.execute(_INDEX)
        self._db.commit()
        self._zc = zstandard.ZstdCompressor()
        self._zd = zstandard.ZstdDecompressor()

    def enqueue(self, payloads: Iterable[Mapping[str, Any]]) -> int:
        """Store readings; returns how many were new."""
        now = self.clock().isoformat()
        rows = []
        for p in payloads:
            blob = json.dumps(p, separators=(",", ":"), default=str).encode()
            rows.append((idempotency_key(p), new_record_id(), str(p["hdt_id"]),
                         self._zc.compress(blob), PENDING, now))
        with self._lock:
            before = self._db.total_changes
            self._db.executemany(
                "INSERT OR IGNORE INTO outbox (key, record_id, hdt_id, payload, status, "
                "enqueued_at) VALUES (?, ?, ?, ?, ?, ?)", rows)
            self._db.commit()
            return self._db.total_changes - before

    def pending(self, limit: int) -> list[Row]:
        with self._lock:
            rows = self._db.execute(
                "SELECT seq, key, record_id, payload FROM outbox WHERE status = ? "
                "ORDER BY seq LIMIT ?", (PENDING, limit)).fetchall()
        return [Row(seq, key, rid, json.loads(self._zd.decompress(blob)))
                for seq, key, rid, blob in rows]

    def attempted(self, rows: Sequence[Row]) -> None:
        with self._lock:
            self._db.executemany("UPDATE outbox SET attempts = attempts + 1 WHERE seq = ?",
                                 [(r.seq,) for r in rows])
            self._db.commit()

    def acknowledge(self, rows: Sequence[Row], rejected_ids: Iterable[str] = ()) -> None:
        rejected = set(rejected_ids)
        now = self.clock().isoformat()
        with self._lock:
            self._db.executemany(
                "UPDATE outbox SET status = ?, acked_at = ?, attempts = attempts + 1 "
                "WHERE seq = ?",
                [(REJECTED if r.record_id in rejected else ACKED, now, r.seq) for r in rows])
            self._db.commit()

    def counts(self) -> dict[str, int]:
        with self._lock:
            rows = self._db.execute("SELECT status, COUNT(*) FROM outbox GROUP BY status")
            out = {PENDING: 0, ACKED: 0, REJECTED: 0}
            out.update({status: n for status, n in rows})
        return out

    def oldest_pending(self) -> datetime | None:
        with self._lock:
            row = self._db.execute("SELECT MIN(enqueued_at) FROM outbox WHERE status = ?",
                                   (PENDING,)).fetchone()
        return datetime.fromisoformat(row[0]) if row and row[0] else None

    def close(self) -> None:
        self._db.close()


@dataclass
class DrainResult:
    sent: int = 0
    accepted: int = 0
    duplicates: int = 0
    rejected: int = 0
    link_down: bool = False


class Forwarder:
    def __init__(self, outbox: Outbox, ingestor: Ingestor, *, batch_size: int = 500) -> None:
        self.outbox = outbox
        self.ingestor = ingestor
        self.batch_size = batch_size

    async def drain(self, *, batch_size: int | None = None) -> DrainResult:
        """Send pending rows until none are left or the link is down."""
        result = DrainResult()
        while rows := self.outbox.pending(batch_size or self.batch_size):
            try:
                ack = await self.ingestor.ingest([r.observation() for r in rows])
            except LinkDown:
                self.outbox.attempted(rows)
                result.link_down = True
                return result
            self.outbox.acknowledge(rows, ack.rejected_ids)
            result.sent += len(rows)
            result.accepted += ack.accepted
            result.duplicates += ack.duplicates
            result.rejected += ack.rejected
        return result
