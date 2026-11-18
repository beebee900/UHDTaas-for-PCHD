"""Backend selection from settings (design 02, section 2.3).

`Backends(settings, service)` builds each backend on first use from the switch
`ATRA_BACKEND__<NAME>`. Data of in-process backends lives under `var/data/<service>/`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from functools import cached_property
from pathlib import Path
from typing import Any

from atra.backends.base import (
    CacheBackend,
    EventBusBackend,
    FhirBackend,
    GraphBackend,
    IdentityBackend,
    ImagingBackend,
    ModelRegistryBackend,
    ObjectBackend,
    PolicyBackend,
    RelationalBackend,
    SchemaRegistryBackend,
    SecretBackend,
    TimeSeriesBackend,
    VectorBackend,
    WorkflowBackend,
)
from atra.config import Settings
from atra.security import Keyring, LocalIssuer


class BackendUnavailable(RuntimeError):
    """The selected container backend is not part of this profile."""


def _pick[T](name: str, choice: str, options: dict[str, Callable[[], T]]) -> T:
    try:
        return options[choice]()
    except KeyError:
        raise BackendUnavailable(f"backend {name}={choice} is not available") from None


class Backends:
    """Lazily built backends of one service process."""

    def __init__(self, settings: Settings, service: str, *, ephemeral: bool = False) -> None:
        self.settings = settings
        self.service = service
        self.ephemeral = ephemeral

    @property
    def data_dir(self) -> Path:
        return self.settings.var_dir / "data" / self.service

    def _file(self, name: str) -> Path | None:
        return None if self.ephemeral else self.data_dir / name

    @cached_property
    def issuer(self) -> LocalIssuer:
        sec = self.settings.security
        key = None if self.ephemeral else self.settings.var_dir / "keys" / "issuer.pem"
        return LocalIssuer(sec.issuer, sec.audience, key_path=key, ttl_s=sec.token_ttl_s)

    @cached_property
    def timeseries(self) -> TimeSeriesBackend:
        from atra.backends.memory import MemoryTimeSeries

        return _pick("timeseries", self.settings.backend.timeseries,
                     {"memory": MemoryTimeSeries})

    @cached_property
    def fhir(self) -> FhirBackend:
        from atra.backends.memory import MemoryFhir

        return _pick("fhir", self.settings.backend.fhir,
                     {"memory": lambda: MemoryFhir(self._file("fhir.sqlite"))})

    @cached_property
    def graph(self) -> GraphBackend:
        from atra.backends.graph import Neo4jGraph, NetworkXGraph

        password = os.environ.get("ATRA_NEO4J_PASSWORD", "atra-neo4j")
        return _pick("graph", self.settings.backend.graph, {
            "memory": NetworkXGraph,
            "neo4j": lambda: Neo4jGraph(self.settings.infra.neo4j, "neo4j", password)})

    @cached_property
    def vector(self) -> VectorBackend:
        from atra.backends.memory import QdrantVectors

        return _pick("vector", self.settings.backend.vector, {
            "memory": lambda: QdrantVectors(path=self._file("qdrant")),
            "qdrant": lambda: QdrantVectors(url=self.settings.infra.qdrant)})

    @cached_property
    def objects(self) -> ObjectBackend:
        from atra.backends.memory import LocalObjects

        root = self.data_dir / "objects"
        if self.ephemeral:
            import tempfile

            root = Path(tempfile.mkdtemp(prefix=f"atra-{self.service}-objects-"))
        return _pick("object", self.settings.backend.object, {"memory": lambda: LocalObjects(root)})

    @cached_property
    def relational(self) -> RelationalBackend:
        from atra.backends.memory import SqliteRelational

        return _pick("relational", self.settings.backend.relational,
                     {"memory": lambda: SqliteRelational(self._file("db.sqlite"))})

    @cached_property
    def cache(self) -> CacheBackend:
        from atra.backends.memory import MemoryCache

        return _pick("cache", self.settings.backend.cache, {"memory": MemoryCache})

    @cached_property
    def events(self) -> EventBusBackend:
        from atra.backends.memory import DyonEventBus

        return _pick("bus", self.settings.backend.bus,
                     {"memory": lambda: DyonEventBus(source_layer=self.service)})

    @cached_property
    def transport(self) -> Any:
        """Connector transport (the supplied `Transport` classes)."""
        from atra.connectors import InMemoryTransport, KafkaTransport, MQTTTransport

        infra = self.settings.infra
        return _pick("bus", self.settings.backend.bus, {
            "memory": InMemoryTransport,
            "kafka": lambda: KafkaTransport(infra.kafka, group_id=f"atra-{self.service}"),
            "mqtt": lambda: MQTTTransport(infra.mqtt)})

    @cached_property
    def schemas(self) -> SchemaRegistryBackend:
        from atra.backends.apicurio import ApicurioSchemaRegistry
        from atra.backends.memory import FileSchemaRegistry

        directory = self.settings.contracts_dir / "schemas" / "connectors"
        return _pick("schema_registry", self.settings.backend.schema_registry, {
            "memory": lambda: FileSchemaRegistry(directory),
            "apicurio": lambda: ApicurioSchemaRegistry(self.settings.infra.apicurio)})

    @cached_property
    def policy(self) -> PolicyBackend:
        from atra.backends.memory import OPAPolicyBackend

        url = self.settings.infra.opa
        return _pick("policy", self.settings.backend.policy, {
            "memory": lambda: OPAPolicyBackend(url), "opa": lambda: OPAPolicyBackend(url)})

    @cached_property
    def identity(self) -> IdentityBackend:
        from atra.backends.memory import LocalIdentity

        return _pick("identity", self.settings.backend.identity,
                     {"memory": lambda: LocalIdentity(self.issuer)})

    @cached_property
    def secrets(self) -> SecretBackend:
        from atra.backends.memory import LocalSecrets

        ring = None if self.ephemeral else self.settings.var_dir / "keys" / "keyring.json"
        return _pick("secret", self.settings.backend.secret,
                     {"memory": lambda: LocalSecrets(Keyring(ring))})

    @cached_property
    def workflows(self) -> WorkflowBackend:
        from atra.backends.memory import MemoryWorkflows

        return _pick("workflow", self.settings.backend.workflow,
                     {"memory": lambda: MemoryWorkflows(self._file("workflows.sqlite"))})

    @cached_property
    def models(self) -> ModelRegistryBackend:
        from atra.backends.memory import FileModelRegistry

        path = None if self.ephemeral else self.settings.var_dir / "registry" / "models.json"
        return _pick("model_registry", self.settings.backend.model_registry,
                     {"memory": lambda: FileModelRegistry(path)})

    @cached_property
    def imaging(self) -> ImagingBackend:
        from atra.backends.memory import LocalDicom

        root = self.data_dir / "dicom"
        base = f"{self.settings.services.ahdt}/dicom-web"
        return _pick("imaging", self.settings.backend.imaging,
                     {"memory": lambda: LocalDicom(root, base_url=base)})

    async def close(self) -> None:
        for name in ("events", "workflows", "relational", "graph"):
            if name in self.__dict__:
                await getattr(self, name).close()
        for name in ("vector", "policy"):
            close = getattr(self.__dict__.get(name), "close", None)
            if close is not None:
                await close()
