"""Backend interfaces (design 02, section 2.3).

Every Python component reaches infrastructure only through these interfaces, so each
piece can run in-process (profile p0) or against its container.
"""

from __future__ import annotations

import abc
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

from atra.contracts import EventEnvelope, ModelRegistryEntry
from atra.policy import PolicyDecision
from atra.security import TokenVerifier

type Aggregate = Literal["raw", "1m", "5m", "1h"]
type Scalar = float | str | bool


@dataclass(frozen=True)
class TSPoint:
    t: datetime
    v: Scalar
    unit: str
    quality: str = "ok"
    version: int = 1
    recorded_at: datetime | None = None


class TimeSeriesBackend(abc.ABC):
    @abc.abstractmethod
    async def write(self, hdt_id: str, code: str, points: Sequence[TSPoint]) -> int: ...

    @abc.abstractmethod
    async def query(self, hdt_id: str, code: str, *, start: datetime | None = None,
                    end: datetime | None = None, aggregate: Aggregate = "raw",
                    as_of: datetime | None = None) -> list[TSPoint]:
        """Points in [start, end]. `as_of` returns what was recorded at that time (replay)."""

    @abc.abstractmethod
    async def latest(self, hdt_id: str, code: str) -> TSPoint | None: ...

    @abc.abstractmethod
    async def codes(self, hdt_id: str) -> list[str]: ...


class FhirBackend(abc.ABC):
    """FHIR R4 resource store. Partitions separate tenants (HAPI partitions)."""

    @abc.abstractmethod
    async def create(self, resource: Mapping[str, Any], *,
                     partition: str = "default") -> dict[str, Any]: ...

    @abc.abstractmethod
    async def read(self, resource_type: str, resource_id: str, *,
                   partition: str = "default") -> dict[str, Any]: ...

    @abc.abstractmethod
    async def update(self, resource: Mapping[str, Any], *,
                     partition: str = "default") -> dict[str, Any]: ...

    @abc.abstractmethod
    async def search(self, resource_type: str, params: Mapping[str, str] | None = None, *,
                     partition: str = "default") -> list[dict[str, Any]]:
        """Supported parameters: `subject`/`patient`, `code`, `status`, `category`,
        `date` with `ge`/`le`/`gt`/`lt`/`eq` prefixes, `encounter`, `_tag`, `_id`."""

    @abc.abstractmethod
    async def history(self, resource_type: str, resource_id: str, *,
                      partition: str = "default") -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    async def delete(self, resource_type: str, resource_id: str, *,
                     partition: str = "default") -> None: ...


class GraphBackend(abc.ABC):
    """Property graph queried with Cypher (the in-process subset is fixed in design 03, 3.12)."""

    @abc.abstractmethod
    async def run(self, query: str, params: Mapping[str, Any] | None = None
                  ) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


@dataclass(frozen=True)
class VectorHit:
    id: str
    score: float
    payload: dict[str, Any]


class VectorBackend(abc.ABC):
    @abc.abstractmethod
    async def ensure_collection(self, name: str, dim: int, *,
                                distance: Literal["cosine", "dot", "euclid"] = "cosine"
                                ) -> None: ...

    @abc.abstractmethod
    async def upsert(self, name: str,
                     points: Sequence[tuple[str, Sequence[float], Mapping[str, Any]]]) -> None: ...

    @abc.abstractmethod
    async def search(self, name: str, vector: Sequence[float], *, top_k: int = 5,
                     where: Mapping[str, Any] | None = None) -> list[VectorHit]: ...

    @abc.abstractmethod
    async def delete(self, name: str, ids: Sequence[str]) -> None: ...


class ObjectBackend(abc.ABC):
    @abc.abstractmethod
    async def put(self, key: str, data: bytes, *,
                  content_type: str = "application/octet-stream") -> str: ...

    @abc.abstractmethod
    async def get(self, key: str) -> bytes: ...

    @abc.abstractmethod
    async def exists(self, key: str) -> bool: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    async def list(self, prefix: str = "") -> list[str]: ...


class RelationalBackend(abc.ABC):
    """SQL database reached through SQLAlchemy's async engine."""

    @property
    @abc.abstractmethod
    def url(self) -> str: ...

    @abc.abstractmethod
    def engine(self) -> Any:
        """`sqlalchemy.ext.asyncio.AsyncEngine`."""

    @abc.abstractmethod
    async def close(self) -> None: ...


class CacheBackend(abc.ABC):
    @abc.abstractmethod
    async def get(self, key: str) -> Any: ...

    @abc.abstractmethod
    async def set(self, key: str, value: Any, *, ttl_s: float | None = None) -> None: ...

    @abc.abstractmethod
    async def delete(self, key: str) -> None: ...

    @abc.abstractmethod
    async def delete_prefix(self, prefix: str) -> int: ...


type EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class EventBusBackend(abc.ABC):
    """Events of design 03, 3.8. Patterns match event types with `*` wildcards."""

    @abc.abstractmethod
    async def publish(self, event: EventEnvelope) -> None: ...

    @abc.abstractmethod
    def subscribe(self, pattern: str, handler: EventHandler) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


class SchemaRegistryBackend(abc.ABC):
    @abc.abstractmethod
    async def get(self, subject: str, version: str) -> dict[str, Any]: ...

    @abc.abstractmethod
    async def register(self, subject: str, version: str, schema: Mapping[str, Any]) -> None: ...

    @abc.abstractmethod
    async def versions(self, subject: str) -> list[str]: ...


class PolicyBackend(abc.ABC):
    @abc.abstractmethod
    async def decide(self, package: str, input_: Mapping[str, Any]) -> PolicyDecision: ...


class IdentityBackend(abc.ABC):
    @abc.abstractmethod
    async def verifier(self) -> TokenVerifier: ...


class SecretBackend(abc.ABC):
    """Service secrets plus per-person envelope encryption (Vault transit or local keyring)."""

    @abc.abstractmethod
    async def get_secret(self, name: str) -> str | None: ...

    @abc.abstractmethod
    async def seal(self, key_id: str, plaintext: bytes) -> str: ...

    @abc.abstractmethod
    async def open(self, key_id: str, token: str) -> bytes: ...

    @abc.abstractmethod
    async def shred(self, key_id: str) -> bool: ...


@dataclass
class WorkflowRun:
    run_id: str
    workflow: str
    status: Literal["running", "waiting", "completed", "failed", "cancelled"]
    args: dict[str, Any]
    result: Any = None
    error: str | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    signals: list[dict[str, Any]] = field(default_factory=list)


class WorkflowContext(abc.ABC):
    """What a workflow function may do: durable sleeps, signals and activities."""

    run_id: str

    @abc.abstractmethod
    async def sleep(self, seconds: float) -> None: ...

    @abc.abstractmethod
    async def wait_signal(self, name: str, *, timeout_s: float | None = None) -> Any: ...

    @abc.abstractmethod
    async def activity(self, fn: Callable[..., Awaitable[Any]], *args: Any) -> Any: ...


type WorkflowFn = Callable[..., Awaitable[Any]]


class WorkflowBackend(abc.ABC):
    @abc.abstractmethod
    def register(self, name: str, fn: WorkflowFn) -> None: ...

    @abc.abstractmethod
    async def start(self, name: str, args: Mapping[str, Any], *,
                    run_id: str | None = None) -> str: ...

    @abc.abstractmethod
    async def signal(self, run_id: str, name: str, payload: Any = None) -> None: ...

    @abc.abstractmethod
    async def status(self, run_id: str) -> WorkflowRun: ...

    @abc.abstractmethod
    async def result(self, run_id: str, *, timeout_s: float | None = None) -> Any: ...

    @abc.abstractmethod
    async def cancel(self, run_id: str) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


type Stage = Literal["None", "Staging", "Production", "Archived"]


class ModelRegistryBackend(abc.ABC):
    @abc.abstractmethod
    async def register(self, entry: ModelRegistryEntry, *,
                       metrics: Mapping[str, float] | None = None) -> None: ...

    @abc.abstractmethod
    async def get(self, model_id: str, version: str | None = None) -> ModelRegistryEntry:
        """A version, or the Production version when `version` is None, else the newest."""

    @abc.abstractmethod
    async def list(self, *, twin: str | None = None,
                   tier: str | None = None) -> list[ModelRegistryEntry]: ...

    @abc.abstractmethod
    async def stage(self, model_id: str, version: str) -> Stage: ...

    @abc.abstractmethod
    async def transition(self, model_id: str, version: str, stage: Stage, *, by: str) -> None: ...


class ImagingBackend(abc.ABC):
    """DICOM store with a DICOMweb-shaped read API (QIDO-RS and WADO-RS)."""

    @abc.abstractmethod
    async def store(self, dicom: bytes) -> dict[str, str]:
        """Returns the study, series and SOP instance UIDs."""

    @abc.abstractmethod
    async def search_studies(self, *, patient_id: str | None = None,
                             modality: str | None = None,
                             since: datetime | None = None) -> list[dict[str, Any]]: ...

    @abc.abstractmethod
    async def instances(self, study_uid: str) -> list[dict[str, str]]: ...

    @abc.abstractmethod
    async def retrieve(self, study_uid: str, series_uid: str, sop_uid: str) -> bytes: ...

    @abc.abstractmethod
    def dicomweb_url(self, study_uid: str) -> str: ...
