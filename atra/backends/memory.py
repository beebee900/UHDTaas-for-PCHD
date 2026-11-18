"""In-process backends for profile p0 (design 02, section 2.3)."""

from __future__ import annotations

import asyncio
import bisect
import contextlib
import fnmatch
import json
import os
import shutil
import sqlite3
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from dyon.core.events import DomainEvent, EventBus

from atra.backends.base import (
    Aggregate,
    CacheBackend,
    EventBusBackend,
    EventHandler,
    FhirBackend,
    IdentityBackend,
    ImagingBackend,
    ModelRegistryBackend,
    ObjectBackend,
    PolicyBackend,
    RelationalBackend,
    SchemaRegistryBackend,
    SecretBackend,
    Stage,
    TimeSeriesBackend,
    TSPoint,
    VectorBackend,
    VectorHit,
    WorkflowBackend,
    WorkflowContext,
    WorkflowFn,
    WorkflowRun,
)
from atra.contracts import EventEnvelope, ModelRegistryEntry
from atra.policy import PolicyClient, PolicyDecision
from atra.security import Keyring, LocalIssuer, TokenVerifier

# ---------------------------------------------------------------------------
# Time series
# ---------------------------------------------------------------------------

_BUCKET_S = {"1m": 60, "5m": 300, "1h": 3600}


class MemoryTimeSeries(TimeSeriesBackend):
    """Sorted per-(hdt_id, code) series. Every write keeps its recording time for replay."""

    def __init__(self) -> None:
        self._series: dict[tuple[str, str], list[TSPoint]] = {}
        self._lock = threading.Lock()

    async def write(self, hdt_id: str, code: str, points: Sequence[TSPoint]) -> int:
        now = datetime.now(UTC)
        with self._lock:
            series = self._series.setdefault((hdt_id, code), [])
            for p in points:
                rec = p if p.recorded_at else TSPoint(p.t, p.v, p.unit, p.quality, p.version, now)
                bisect.insort(series, rec, key=lambda x: (x.t, x.version))
        return len(points)

    async def query(self, hdt_id: str, code: str, *, start: datetime | None = None,
                    end: datetime | None = None, aggregate: Aggregate = "raw",
                    as_of: datetime | None = None) -> list[TSPoint]:
        with self._lock:
            series = list(self._series.get((hdt_id, code), []))
        latest: dict[datetime, TSPoint] = {}
        for p in series:
            if (start and p.t < start) or (end and p.t > end):
                continue
            if as_of and p.recorded_at and p.recorded_at > as_of:
                continue
            if p.quality == "rejected":
                continue
            cur = latest.get(p.t)
            if cur is None or p.version >= cur.version:
                latest[p.t] = p
        points = [latest[t] for t in sorted(latest)]
        if aggregate == "raw" or not points:
            return points
        return _aggregate(points, _BUCKET_S[aggregate])

    async def latest(self, hdt_id: str, code: str) -> TSPoint | None:
        points = await self.query(hdt_id, code)
        return points[-1] if points else None

    async def codes(self, hdt_id: str) -> list[str]:
        with self._lock:
            return sorted(code for (h, code) in self._series if h == hdt_id)


def _aggregate(points: Sequence[TSPoint], bucket_s: int) -> list[TSPoint]:
    buckets: dict[int, list[TSPoint]] = {}
    for p in points:
        buckets.setdefault(int(p.t.timestamp()) // bucket_s, []).append(p)
    out: list[TSPoint] = []
    for key in sorted(buckets):
        group = buckets[key]
        t = datetime.fromtimestamp(key * bucket_s, UTC)
        numeric = [float(p.v) for p in group
                   if isinstance(p.v, int | float) and not isinstance(p.v, bool)]
        value: float | str | bool = sum(numeric) / len(numeric) if numeric else group[-1].v
        quality = "suspect" if any(p.quality == "suspect" for p in group) else "ok"
        out.append(TSPoint(t, value, group[-1].unit, quality))
    return out


# ---------------------------------------------------------------------------
# FHIR
# ---------------------------------------------------------------------------

_DATE_PATHS = ("effectiveDateTime", "effectivePeriod.start", "issued", "authoredOn",
               "recordedDate", "onsetDateTime", "period.start", "started",
               "occurrenceDateTime", "dateTime", "date", "whenHandedOver",
               "collection.collectedDateTime")
_CODE_PATHS = ("code", "medicationCodeableConcept", "vaccineCode", "type")


def _get(resource: Mapping[str, Any], path: str) -> Any:
    cur: Any = resource
    for part in path.split("."):
        if not isinstance(cur, Mapping):
            return None
        cur = cur.get(part)
    return cur


def _codings(concept: Any) -> list[Mapping[str, Any]]:
    if isinstance(concept, list):
        return [c for item in concept for c in _codings(item)]
    if isinstance(concept, Mapping):
        return list(concept.get("coding", []))
    return []


def _ref_matches(ref: Any, wanted: str) -> bool:
    if not isinstance(ref, Mapping):
        return False
    value = str(ref.get("reference", ""))
    return value == wanted or value.split("/")[-1] == wanted.split("/")[-1]


def _parse_date(text: str) -> datetime:
    dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _match_date(resource: Mapping[str, Any], expr: str) -> bool:
    prefix = expr[:2] if expr[:2] in {"ge", "le", "gt", "lt", "eq"} else "eq"
    target = _parse_date(expr[2:] if expr[:2] == prefix else expr)
    for path in _DATE_PATHS:
        raw = _get(resource, path)
        if isinstance(raw, str):
            value = _parse_date(raw)
            return {"ge": value >= target, "le": value <= target, "gt": value > target,
                    "lt": value < target, "eq": value == target}[prefix]
    return False


SEARCH_PARAMS = frozenset({"subject", "patient", "encounter", "code", "category", "status",
                           "date", "_id", "_tag"})


def _match_param(resource: Mapping[str, Any], name: str, value: str) -> bool:
    alternatives = value.split(",")
    if name in {"subject", "patient"}:
        return any(_ref_matches(resource.get(field), v) for v in alternatives
                   for field in ("subject", "patient", "beneficiary"))
    if name == "encounter":
        return any(_ref_matches(resource.get("encounter"), v) for v in alternatives)
    if name == "code":
        codings = [c for path in _CODE_PATHS for c in _codings(resource.get(path))]
        for v in alternatives:
            system, _, code = v.rpartition("|")
            if any(c.get("code") == code and (not system or c.get("system") == system)
                   for c in codings):
                return True
        return False
    if name == "category":
        codes = {c.get("code") for c in _codings(resource.get("category"))}
        return bool(codes.intersection(alternatives))
    if name == "status":
        return resource.get("status") in alternatives
    if name == "date":
        return all(_match_date(resource, v) for v in alternatives)
    if name == "_id":
        return resource.get("id") in alternatives
    if name == "_tag":
        meta = resource.get("meta", {})
        tags = {t.get("code") for t in meta.get("tag", []) + meta.get("security", [])}
        return bool(tags.intersection(alternatives))
    raise ValueError(f"unsupported search parameter '{name}'")


class MemoryFhir(FhirBackend):
    """SQLite JSON store of FHIR resources with versions and partitions."""

    def __init__(self, path: Path | None = None) -> None:
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._db.execute(
                "CREATE TABLE IF NOT EXISTS resources (partition TEXT, type TEXT, id TEXT, "
                "version INTEGER, deleted INTEGER, body TEXT, "
                "PRIMARY KEY (partition, type, id, version))")
            self._db.commit()

    def _latest(self, partition: str, rtype: str, rid: str) -> tuple[int, int, str] | None:
        row = self._db.execute(
            "SELECT version, deleted, body FROM resources WHERE partition=? AND type=? AND id=? "
            "ORDER BY version DESC LIMIT 1", (partition, rtype, rid)).fetchone()
        return None if row is None else (int(row[0]), int(row[1]), str(row[2]))

    def _put(self, partition: str, resource: dict[str, Any], version: int,
             deleted: bool = False) -> dict[str, Any]:
        resource = dict(resource)
        meta = dict(resource.get("meta", {}))
        meta.update({"versionId": str(version),
                     "lastUpdated": datetime.now(UTC).isoformat(timespec="milliseconds")})
        resource["meta"] = meta
        self._db.execute("INSERT INTO resources VALUES (?, ?, ?, ?, ?, ?)",
                         (partition, resource["resourceType"], resource["id"], version,
                          int(deleted), json.dumps(resource)))
        self._db.commit()
        return resource

    async def create(self, resource: Mapping[str, Any], *,
                     partition: str = "default") -> dict[str, Any]:
        body = dict(resource)
        if "resourceType" not in body:
            raise ValueError("resourceType is required")
        body.setdefault("id", uuid.uuid4().hex)
        with self._lock:
            if self._latest(partition, body["resourceType"], body["id"]) is not None:
                raise FileExistsError(f"{body['resourceType']}/{body['id']} exists")
            return self._put(partition, body, 1)

    async def read(self, resource_type: str, resource_id: str, *,
                   partition: str = "default") -> dict[str, Any]:
        with self._lock:
            row = self._latest(partition, resource_type, resource_id)
        if row is None or row[1]:
            raise KeyError(f"{resource_type}/{resource_id}")
        result: dict[str, Any] = json.loads(row[2])
        return result

    async def update(self, resource: Mapping[str, Any], *,
                     partition: str = "default") -> dict[str, Any]:
        body = dict(resource)
        with self._lock:
            row = self._latest(partition, body["resourceType"], body["id"])
            return self._put(partition, body, 1 if row is None else row[0] + 1)

    async def search(self, resource_type: str, params: Mapping[str, str] | None = None, *,
                     partition: str = "default") -> list[dict[str, Any]]:
        unknown = set(params or {}) - SEARCH_PARAMS
        if unknown:
            raise ValueError(f"unsupported search parameters {sorted(unknown)}")
        with self._lock:
            rows = self._db.execute(
                "SELECT r.body, r.deleted FROM resources r JOIN (SELECT id, MAX(version) v "
                "FROM resources WHERE partition=? AND type=? GROUP BY id) m "
                "ON r.id = m.id AND r.version = m.v WHERE r.partition=? AND r.type=?",
                (partition, resource_type, partition, resource_type)).fetchall()
        out = []
        for body, deleted in rows:
            if deleted:
                continue
            res = json.loads(body)
            if all(_match_param(res, k, v) for k, v in (params or {}).items()):
                out.append(res)
        return out

    async def history(self, resource_type: str, resource_id: str, *,
                      partition: str = "default") -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT body FROM resources WHERE partition=? AND type=? AND id=? "
                "ORDER BY version", (partition, resource_type, resource_id)).fetchall()
        return [json.loads(r[0]) for r in rows]

    async def delete(self, resource_type: str, resource_id: str, *,
                     partition: str = "default") -> None:
        with self._lock:
            row = self._latest(partition, resource_type, resource_id)
            if row is None:
                raise KeyError(f"{resource_type}/{resource_id}")
            body = json.loads(row[2])
            self._put(partition, body, row[0] + 1, deleted=True)


# ---------------------------------------------------------------------------
# Vector store (qdrant-client local mode)
# ---------------------------------------------------------------------------

def _point_uuid(point_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"atra:{point_id}"))


class QdrantVectors(VectorBackend):
    """Qdrant through `qdrant-client`: local mode (`path` or memory) in p0, a server otherwise."""

    def __init__(self, *, path: Path | None = None, url: str | None = None) -> None:
        from qdrant_client import AsyncQdrantClient

        if url:
            self._client = AsyncQdrantClient(url=url)
        elif path is not None:
            path.mkdir(parents=True, exist_ok=True)
            self._client = AsyncQdrantClient(path=str(path))
        else:
            self._client = AsyncQdrantClient(location=":memory:")

    async def ensure_collection(self, name: str, dim: int, *,
                                distance: Literal["cosine", "dot", "euclid"] = "cosine"
                                ) -> None:
        from qdrant_client import models

        if await self._client.collection_exists(name):
            return
        metric = {"cosine": models.Distance.COSINE, "dot": models.Distance.DOT,
                  "euclid": models.Distance.EUCLID}[distance]
        await self._client.create_collection(
            name, vectors_config=models.VectorParams(size=dim, distance=metric))

    async def upsert(self, name: str,
                     points: Sequence[tuple[str, Sequence[float], Mapping[str, Any]]]) -> None:
        from qdrant_client import models

        await self._client.upsert(name, points=[
            models.PointStruct(id=_point_uuid(pid), vector=list(vec),
                               payload={**payload, "_id": pid})
            for pid, vec, payload in points])

    async def search(self, name: str, vector: Sequence[float], *, top_k: int = 5,
                     where: Mapping[str, Any] | None = None) -> list[VectorHit]:
        from qdrant_client import models

        flt = None
        if where:
            flt = models.Filter(must=[
                models.FieldCondition(key=k, match=models.MatchAny(any=list(v))
                                      if isinstance(v, list | tuple)
                                      else models.MatchValue(value=v))
                for k, v in where.items()])
        res = await self._client.query_points(name, query=list(vector), limit=top_k,
                                              query_filter=flt, with_payload=True)
        hits = []
        for p in res.points:
            payload = dict(p.payload or {})
            hits.append(VectorHit(str(payload.pop("_id", p.id)), float(p.score), payload))
        return hits

    async def delete(self, name: str, ids: Sequence[str]) -> None:
        from qdrant_client import models

        await self._client.delete(name, points_selector=models.PointIdsList(
            points=[_point_uuid(i) for i in ids]))

    async def close(self) -> None:
        await self._client.close()


# ---------------------------------------------------------------------------
# Objects, relational, cache
# ---------------------------------------------------------------------------

class LocalObjects(ObjectBackend):
    """Objects as files under one directory; keys are relative paths."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if not path.is_relative_to(self.root) or path == self.root:
            raise ValueError(f"invalid object key '{key}'")
        return path

    async def put(self, key: str, data: bytes, *,
                  content_type: str = "application/octet-stream") -> str:
        path = self._path(key)
        await asyncio.to_thread(_atomic_write, path, data)
        return key

    async def get(self, key: str) -> bytes:
        path = self._path(key)
        if not path.is_file():
            raise KeyError(key)
        return await asyncio.to_thread(path.read_bytes)

    async def exists(self, key: str) -> bool:
        return self._path(key).is_file()

    async def delete(self, key: str) -> None:
        self._path(key).unlink(missing_ok=True)

    async def list(self, prefix: str = "") -> list[str]:
        return sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")
                      if p.is_file() and str(p.relative_to(self.root)).startswith(prefix))


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data)
    tmp.replace(path)


class SqliteRelational(RelationalBackend):
    """SQLite through SQLAlchemy's aiosqlite dialect; in memory when no path is given.

    SQLAlchemy invalidates a connection when a task is cancelled inside a statement. The
    in-memory database is therefore a named shared-cache database that an anchor connection
    keeps open, so the replacement connection sees the same tables and rows.
    """

    def __init__(self, path: Path | None = None) -> None:
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            self._url = f"sqlite+aiosqlite:///{path}"
            self._memory = ""
        else:
            self._memory = f"file:atra-{uuid.uuid4().hex}?mode=memory&cache=shared"
            self._url = f"sqlite+aiosqlite:///{self._memory}&uri=true"
        self._engine: Any = None
        self._anchor: sqlite3.Connection | None = None

    @property
    def url(self) -> str:
        return self._url

    def engine(self) -> Any:
        if self._engine is None:
            from sqlalchemy.ext.asyncio import create_async_engine
            from sqlalchemy.pool import StaticPool

            if self._memory:
                self._anchor = sqlite3.connect(self._memory, uri=True, check_same_thread=False)
                self._engine = create_async_engine(self._url, poolclass=StaticPool)
            else:
                self._engine = create_async_engine(self._url)
        return self._engine

    async def close(self) -> None:
        if self._engine is not None:
            await self._engine.dispose()
            self._engine = None
        if self._anchor is not None:
            self._anchor.close()
            self._anchor = None


class MemoryCache(CacheBackend):
    def __init__(self) -> None:
        self._values: dict[str, tuple[float | None, Any]] = {}
        self._lock = threading.Lock()

    async def get(self, key: str) -> Any:
        with self._lock:
            item = self._values.get(key)
            if item is None:
                return None
            expires, value = item
            if expires is not None and expires < time.monotonic():
                del self._values[key]
                return None
            return value

    async def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None:
        with self._lock:
            self._values[key] = (None if ttl_s is None else time.monotonic() + ttl_s, value)

    async def delete(self, key: str) -> None:
        with self._lock:
            self._values.pop(key, None)

    async def delete_prefix(self, prefix: str) -> int:
        with self._lock:
            keys = [k for k in self._values if k.startswith(prefix)]
            for k in keys:
                del self._values[k]
            return len(keys)


# ---------------------------------------------------------------------------
# Events
# ---------------------------------------------------------------------------

class DyonEventBus(EventBusBackend):
    """Design 03, 3.8 events on Dyon's in-process `EventBus`."""

    def __init__(self, bus: EventBus | None = None, *, source_layer: str = "atra") -> None:
        self.bus = bus or EventBus()
        self.source_layer = source_layer
        self.published: list[EventEnvelope] = []

    async def publish(self, event: EventEnvelope) -> None:
        self.published.append(event)
        await self.bus.publish(DomainEvent(
            event_type=event.event_type, source_layer=self.source_layer,
            source_asset=event.hdt_id or event.source,
            payload={"envelope": event.model_dump(mode="json")}, timestamp=event.wall_time))

    def subscribe(self, pattern: str, handler: EventHandler) -> None:
        async def deliver(ev: DomainEvent) -> None:
            envelope = EventEnvelope.model_validate(ev.payload["envelope"])
            if fnmatch.fnmatchcase(envelope.event_type, pattern):
                await handler(envelope)

        self.bus.subscribe("*" if any(ch in pattern for ch in "*?[") else pattern, deliver)

    async def drain(self, timeout_s: float = 300.0) -> None:
        """Wait until every handler started so far has finished. The limit is long because
        a handler can refresh and explain a twin, which takes minutes on a loaded machine."""
        await self.bus.aclose(timeout=timeout_s)

    async def close(self) -> None:
        await self.bus.aclose()


# ---------------------------------------------------------------------------
# Schema registry, policy, identity, secrets
# ---------------------------------------------------------------------------

class FileSchemaRegistry(SchemaRegistryBackend):
    """Connector contract schemas from `contracts/schemas/connectors/`."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._overlay: dict[tuple[str, str], dict[str, Any]] = {}

    async def get(self, subject: str, version: str) -> dict[str, Any]:
        if (subject, version) in self._overlay:
            return self._overlay[(subject, version)]
        path = self.directory / f"{subject}.v{version}.schema.json"
        if not path.exists():
            raise KeyError(f"{subject} v{version}")
        result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return result

    async def register(self, subject: str, version: str, schema: Mapping[str, Any]) -> None:
        self._overlay[(subject, version)] = dict(schema)

    async def versions(self, subject: str) -> list[str]:
        found = {p.name[len(subject) + 2:-len(".schema.json")]
                 for p in self.directory.glob(f"{subject}.v*.schema.json")}
        found.update(v for s, v in self._overlay if s == subject)
        return sorted(found, key=lambda v: tuple(int(x) for x in v.split(".")))


class OPAPolicyBackend(PolicyBackend):
    """OPA over HTTP: the local OPA process in p0, the OPA container in p2."""

    def __init__(self, url: str) -> None:
        self.client = PolicyClient(url)

    async def decide(self, package: str, input_: Mapping[str, Any]) -> PolicyDecision:
        return await self.client.decide(package, input_)

    async def close(self) -> None:
        await self.client.aclose()


class LocalIdentity(IdentityBackend):
    def __init__(self, issuer: LocalIssuer) -> None:
        self.issuer = issuer

    async def verifier(self) -> TokenVerifier:
        return TokenVerifier(self.issuer.jwks(), issuer=self.issuer.issuer,
                             audience=self.issuer.audience)


class LocalSecrets(SecretBackend):
    """Secrets from `ATRA_SECRET__<NAME>` variables; transit from the local keyring."""

    def __init__(self, keyring: Keyring) -> None:
        self.keyring = keyring

    async def get_secret(self, name: str) -> str | None:
        return os.environ.get(f"ATRA_SECRET__{name.upper()}")

    async def seal(self, key_id: str, plaintext: bytes) -> str:
        return self.keyring.seal(key_id, plaintext)

    async def open(self, key_id: str, token: str) -> bytes:
        return self.keyring.open(key_id, token)

    async def shred(self, key_id: str) -> bool:
        return self.keyring.shred(key_id)


# ---------------------------------------------------------------------------
# Workflows: asyncio with SQLite persistence and replay
# ---------------------------------------------------------------------------

class _MemoryWorkflowContext(WorkflowContext):
    """Each step (activity, sleep, signal) is memoised by sequence number, so a run that
    restarts after a crash replays completed steps from the store instead of redoing them."""

    def __init__(self, backend: MemoryWorkflows, run_id: str) -> None:
        self.backend = backend
        self.run_id = run_id
        self._seq = 0

    def _next(self) -> int:
        self._seq += 1
        return self._seq

    async def activity(self, fn: Callable[..., Awaitable[Any]], *args: Any) -> Any:
        seq = self._next()
        found, value = self.backend._memo_get(self.run_id, seq)
        if found:
            return value
        result = await fn(*args)
        self.backend._memo_put(self.run_id, seq, result)
        return result

    async def sleep(self, seconds: float) -> None:
        seq = self._next()
        found, wake = self.backend._memo_get(self.run_id, seq)
        if not found:
            wake = time.time() + seconds * self.backend.time_scale
            self.backend._memo_put(self.run_id, seq, wake)
        remaining = float(wake) - time.time()
        if remaining > 0:
            self.backend._set_status(self.run_id, "waiting")
            await asyncio.sleep(remaining)
            self.backend._set_status(self.run_id, "running")

    async def wait_signal(self, name: str, *, timeout_s: float | None = None) -> Any:
        seq = self._next()
        found, value = self.backend._memo_get(self.run_id, seq)
        if found:
            return value
        self.backend._set_status(self.run_id, "waiting")
        payload = await self.backend._take_signal(self.run_id, name, timeout_s)
        self.backend._set_status(self.run_id, "running")
        self.backend._memo_put(self.run_id, seq, payload)
        return payload


class MemoryWorkflows(WorkflowBackend):
    """Durable workflows for p0: the same workflow functions as the Temporal workers.

    `time_scale` shrinks durable sleeps (for example 1/240 to follow the simulation clock).
    """

    def __init__(self, path: Path | None = None, *, time_scale: float = 1.0) -> None:
        if path is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self._lock = threading.Lock()
        self.time_scale = time_scale
        self._fns: dict[str, WorkflowFn] = {}
        self._tasks: dict[str, asyncio.Task[Any]] = {}
        self._signal_events: dict[str, asyncio.Event] = {}
        self._cancelling: set[str] = set()
        with self._lock:
            self._db.executescript(
                "CREATE TABLE IF NOT EXISTS runs (run_id TEXT PRIMARY KEY, workflow TEXT, "
                "status TEXT, args TEXT, result TEXT, error TEXT, started REAL, finished REAL);"
                "CREATE TABLE IF NOT EXISTS memo (run_id TEXT, seq INTEGER, value TEXT, "
                "PRIMARY KEY (run_id, seq));"
                "CREATE TABLE IF NOT EXISTS signals (id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "run_id TEXT, name TEXT, payload TEXT, consumed INTEGER DEFAULT 0);")
            self._db.commit()

    def register(self, name: str, fn: WorkflowFn) -> None:
        self._fns[name] = fn

    async def start(self, name: str, args: Mapping[str, Any], *,
                    run_id: str | None = None) -> str:
        if name not in self._fns:
            raise KeyError(f"workflow '{name}' is not registered")
        rid = run_id or f"wf-{uuid.uuid4().hex}"
        with self._lock:
            self._db.execute("INSERT INTO runs VALUES (?, ?, 'running', ?, NULL, NULL, ?, NULL)",
                             (rid, name, json.dumps(dict(args), default=str), time.time()))
            self._db.commit()
        self._launch(rid, name, dict(args))
        return rid

    def _launch(self, rid: str, name: str, args: dict[str, Any]) -> None:
        self._tasks[rid] = asyncio.create_task(self._run(rid, name, args))

    async def recover(self) -> list[str]:
        """Restart every unfinished run whose workflow is registered (after a process restart)."""
        with self._lock:
            rows = self._db.execute(
                "SELECT run_id, workflow, args FROM runs WHERE status IN ('running', 'waiting')"
            ).fetchall()
        resumed = []
        for rid, name, args in rows:
            if name in self._fns and rid not in self._tasks:
                self._launch(rid, name, json.loads(args))
                resumed.append(rid)
        return resumed

    async def _run(self, rid: str, name: str, args: dict[str, Any]) -> None:
        ctx = _MemoryWorkflowContext(self, rid)
        try:
            result = await self._fns[name](ctx, **args)
        except asyncio.CancelledError:
            if rid in self._cancelling:
                self._finish(rid, "cancelled", None, None)
                return
            raise
        except Exception as exc:
            self._finish(rid, "failed", None, f"{type(exc).__name__}: {exc}")
            return
        self._finish(rid, "completed", result, None)

    def _finish(self, rid: str, status: str, result: Any, error: str | None) -> None:
        with self._lock:
            self._db.execute("UPDATE runs SET status=?, result=?, error=?, finished=? "
                             "WHERE run_id=?",
                             (status, json.dumps(result, default=str), error, time.time(), rid))
            self._db.commit()

    def _set_status(self, rid: str, status: str) -> None:
        with self._lock:
            self._db.execute("UPDATE runs SET status=? WHERE run_id=? AND status IN "
                             "('running', 'waiting')", (status, rid))
            self._db.commit()

    def _memo_get(self, rid: str, seq: int) -> tuple[bool, Any]:
        with self._lock:
            row = self._db.execute("SELECT value FROM memo WHERE run_id=? AND seq=?",
                                   (rid, seq)).fetchone()
        return (False, None) if row is None else (True, json.loads(row[0]))

    def _memo_put(self, rid: str, seq: int, value: Any) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO memo VALUES (?, ?, ?)",
                             (rid, seq, json.dumps(value, default=str)))
            self._db.commit()

    async def _take_signal(self, rid: str, name: str, timeout_s: float | None) -> Any:
        deadline = None if timeout_s is None else time.monotonic() + timeout_s
        while True:
            with self._lock:
                row = self._db.execute(
                    "SELECT id, payload FROM signals WHERE run_id=? AND name=? AND consumed=0 "
                    "ORDER BY id LIMIT 1", (rid, name)).fetchone()
                if row is not None:
                    self._db.execute("UPDATE signals SET consumed=1 WHERE id=?", (row[0],))
                    self._db.commit()
                    return json.loads(row[1])
            event = self._signal_events.setdefault(rid, asyncio.Event())
            event.clear()
            wait = None if deadline is None else deadline - time.monotonic()
            if wait is not None and wait <= 0:
                raise TimeoutError(f"no '{name}' signal for {rid}")
            try:
                await asyncio.wait_for(event.wait(), wait)
            except TimeoutError:
                raise TimeoutError(f"no '{name}' signal for {rid}") from None

    async def signal(self, run_id: str, name: str, payload: Any = None) -> None:
        with self._lock:
            if self._db.execute("SELECT 1 FROM runs WHERE run_id=?", (run_id,)).fetchone() is None:
                raise KeyError(run_id)
            self._db.execute("INSERT INTO signals (run_id, name, payload) VALUES (?, ?, ?)",
                             (run_id, name, json.dumps(payload, default=str)))
            self._db.commit()
        self._signal_events.setdefault(run_id, asyncio.Event()).set()

    async def status(self, run_id: str) -> WorkflowRun:
        with self._lock:
            row = self._db.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
            sigs = self._db.execute("SELECT name, payload, consumed FROM signals WHERE run_id=? "
                                    "ORDER BY id", (run_id,)).fetchall()
        if row is None:
            raise KeyError(run_id)
        rid, wf, status, args, result, error, started, finished = row
        return WorkflowRun(
            rid, wf, status, json.loads(args), None if result is None else json.loads(result),
            error, datetime.fromtimestamp(started, UTC),
            None if finished is None else datetime.fromtimestamp(finished, UTC),
            [{"name": n, "payload": json.loads(p), "consumed": bool(c)} for n, p, c in sigs])

    async def result(self, run_id: str, *, timeout_s: float | None = None) -> Any:
        task = self._tasks.get(run_id)
        if task is not None:
            await asyncio.wait_for(asyncio.shield(task), timeout_s)
        run = await self.status(run_id)
        if run.status == "failed":
            raise RuntimeError(run.error)
        return run.result

    async def cancel(self, run_id: str) -> None:
        task = self._tasks.get(run_id)
        if task is not None and not task.done():
            self._cancelling.add(run_id)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        else:
            self._finish(run_id, "cancelled", None, None)

    async def close(self) -> None:
        """Stop running workflows without finishing them; `recover()` resumes them later."""
        for task in self._tasks.values():
            if not task.done():
                task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()


# ---------------------------------------------------------------------------
# Model registry: JSON file
# ---------------------------------------------------------------------------

class FileModelRegistry(ModelRegistryBackend):
    """Model registry in one JSON file, with MLflow's stages (p0 unit tests and demos)."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        if path is not None and path.exists():
            self._data = json.loads(path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        if self.path is not None:
            _atomic_write(self.path, json.dumps(self._data, indent=1, sort_keys=True).encode())

    async def register(self, entry: ModelRegistryEntry, *,
                       metrics: Mapping[str, float] | None = None) -> None:
        with self._lock:
            versions = self._data.setdefault(entry.model_id, {})
            previous = versions.get(entry.version, {})
            versions[entry.version] = {"entry": entry.model_dump(mode="json", by_alias=True),
                                       "stage": previous.get("stage", "None"),
                                       "metrics": dict(metrics or {}),
                                       "history": previous.get("history", [])}
            self._save()

    async def get(self, model_id: str, version: str | None = None) -> ModelRegistryEntry:
        with self._lock:
            versions = self._data.get(model_id)
            if not versions:
                raise KeyError(model_id)
            if version is None:
                prod = [v for v, rec in versions.items() if rec["stage"] == "Production"]
                version = prod[0] if prod else max(versions, key=_semver)
            rec = versions.get(version)
        if rec is None:
            raise KeyError(f"{model_id} {version}")
        return ModelRegistryEntry.model_validate(rec["entry"])

    async def list(self, *, twin: str | None = None,
                   tier: str | None = None) -> list[ModelRegistryEntry]:
        with self._lock:
            entries = [ModelRegistryEntry.model_validate(rec["entry"])
                       for versions in self._data.values() for rec in versions.values()]
        return [e for e in entries
                if (twin is None or (e.twin if isinstance(e.twin, str) else e.twin.value) == twin)
                and (tier is None or e.tier.value == tier)]

    async def stage(self, model_id: str, version: str) -> Stage:
        with self._lock:
            stage: Stage = self._data[model_id][version]["stage"]
            return stage

    async def transition(self, model_id: str, version: str, stage: Stage, *, by: str) -> None:
        with self._lock:
            versions = self._data[model_id]
            if stage == "Production":
                for rec in versions.values():
                    if rec["stage"] == "Production":
                        rec["stage"] = "Archived"
            rec = versions[version]
            rec["stage"] = stage
            rec["history"].append({"stage": stage, "by": by,
                                   "at": datetime.now(UTC).isoformat()})
            self._save()


def _semver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split(".") if x.isdigit())


# ---------------------------------------------------------------------------
# Imaging: local DICOM folder
# ---------------------------------------------------------------------------

class LocalDicom(ImagingBackend):
    """DICOM files in `<root>/<study>/<series>/<sop>.dcm` with a DICOMweb-shaped read API."""

    def __init__(self, root: Path, *, base_url: str = "http://127.0.0.1:8100/dicom-web") -> None:
        self.root = root
        self.base_url = base_url.rstrip("/")
        root.mkdir(parents=True, exist_ok=True)

    async def store(self, dicom: bytes) -> dict[str, str]:
        import io

        import pydicom

        ds = pydicom.dcmread(io.BytesIO(dicom), stop_before_pixels=True)
        uids = {"study_uid": str(ds.StudyInstanceUID), "series_uid": str(ds.SeriesInstanceUID),
                "sop_uid": str(ds.SOPInstanceUID)}
        path = self.root / uids["study_uid"] / uids["series_uid"] / f"{uids['sop_uid']}.dcm"
        await asyncio.to_thread(_atomic_write, path, dicom)
        return uids

    def _headers(self) -> list[tuple[Path, Any]]:
        import pydicom

        out = []
        for path in sorted(self.root.glob("*/*/*.dcm")):
            out.append((path, pydicom.dcmread(str(path), stop_before_pixels=True)))
        return out

    async def search_studies(self, *, patient_id: str | None = None,
                             modality: str | None = None,
                             since: datetime | None = None) -> list[dict[str, Any]]:
        headers = await asyncio.to_thread(self._headers)
        studies: dict[str, dict[str, Any]] = {}
        for _path, ds in headers:
            if patient_id and str(getattr(ds, "PatientID", "")) != patient_id:
                continue
            if modality and str(getattr(ds, "Modality", "")) != modality:
                continue
            started = _dicom_datetime(ds)
            if since and started and started < since:
                continue
            uid = str(ds.StudyInstanceUID)
            study = studies.setdefault(uid, {
                "study_uid": uid, "modality": str(getattr(ds, "Modality", "")),
                "started": started.isoformat() if started else None,
                "description": str(getattr(ds, "StudyDescription", "")),
                "dicomweb_url": self.dicomweb_url(uid), "series": set()})
            study["series"].add(str(ds.SeriesInstanceUID))
        return [{**{k: v for k, v in s.items() if k != "series"}, "series_count": len(s["series"])}
                for s in studies.values()]

    async def instances(self, study_uid: str) -> list[dict[str, str]]:
        base = self.root / study_uid
        return [{"study_uid": study_uid, "series_uid": p.parent.name, "sop_uid": p.stem}
                for p in sorted(base.glob("*/*.dcm"))]

    async def retrieve(self, study_uid: str, series_uid: str, sop_uid: str) -> bytes:
        path = self.root / study_uid / series_uid / f"{sop_uid}.dcm"
        if not path.is_file():
            raise KeyError(sop_uid)
        return await asyncio.to_thread(path.read_bytes)

    def dicomweb_url(self, study_uid: str) -> str:
        return f"{self.base_url}/studies/{study_uid}"


def _dicom_datetime(ds: Any) -> datetime | None:
    date = str(getattr(ds, "StudyDate", "") or "")
    if len(date) != 8:
        return None
    clock = str(getattr(ds, "StudyTime", "") or "000000").split(".")[0].ljust(6, "0")
    return datetime.strptime(date + clock[:6], "%Y%m%d%H%M%S").replace(tzinfo=UTC)


def reset_dir(path: Path) -> None:
    """Remove a backend's data directory (used by tests and `make clean-data`)."""
    if path.exists():
        shutil.rmtree(path)


__all__ = [
    "DyonEventBus", "FileModelRegistry", "FileSchemaRegistry", "LocalDicom", "LocalIdentity",
    "LocalObjects", "LocalSecrets", "MemoryCache", "MemoryFhir", "MemoryTimeSeries",
    "MemoryWorkflows", "OPAPolicyBackend", "QdrantVectors", "SqliteRelational", "reset_dir",
]
