"""State shared by the Layer 6 services of one AHDT process (design 04, 4.7.1).

The runtime owns the organ instance store, the model catalogue, the ingest pipeline with its
data lake, the output store and the language model chain. Handlers read and write through it,
so REST, gRPC and MCP calls see one state.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ahdt.ingest.pipeline import IngestPipeline
from ahdt.models.base import Layer4Base
from ahdt.models.catalogue import (
    contributors,
    create_person_instances,
    default_catalogue,
    primary_models,
)
from ahdt.models.coupling import parse, resolve_inputs
from ahdt.models.language.converse import Converser
from ahdt.models.organs.store import ASSIMILATION, InstanceStore
from ahdt.models.reference import default_kb
from ahdt.registry import Registry
from ahdt.services.notify import NotificationRouter
from ahdt.services.observations import ObservationReader, Reading
from ahdt.services.outputs import OutputStore
from atra import contracts as c
from atra.backends import Backends
from atra.config import Settings
from atra.connectors import DTKind
from atra.consent import ConsentRegistry
from atra.personas import PERSONAS
from atra.provenance import AuditLog

type PipelineGetter = Callable[[], Awaitable[IngestPipeline]]


@dataclass
class ResolvedInputs:
    """Model inputs with the ids of the records they came from."""

    values: dict[str, Any] = field(default_factory=dict)
    used: list[str] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)
    """Record id behind each input that came from an observation, by field name."""


class _TolerantFacets:
    """A fork whose missing facets read as empty, so a model runs on what the fork holds."""

    def __init__(self, inner: Any) -> None:
        self.inner = inner

    async def get_facet(self, hdt_id: str, anatomy: str, facet: str, **kw: Any) -> c.FacetView:
        try:
            view: c.FacetView = await self.inner.get_facet(hdt_id, anatomy, facet, **kw)
        except (KeyError, PermissionError):
            return c.FacetView(instance_id="", anatomy=anatomy, facet=facet, fields={},
                               revision=0)
        return view


class Runtime:
    def __init__(self, *, backends: Backends, consents: ConsentRegistry, audit: AuditLog,
                 settings: Settings, registry: Registry, pipeline: PipelineGetter,
                 make_converser: Callable[[], Converser],
                 catalogue: Mapping[str, Layer4Base] | None = None) -> None:
        self.backends = backends
        self.consents = consents
        self.audit = audit
        self.settings = settings
        self.registry = registry
        self._make_converser = make_converser
        self._converser: Converser | None = None
        self.languages: dict[str, str] = {p.hdt_id: p.language for p in PERSONAS}
        self.catalogue = dict(catalogue) if catalogue is not None else default_catalogue()
        self.kb = default_kb()
        self.notifier = NotificationRouter(backends, consents)
        self.store = InstanceStore(registry)
        self.contributors = contributors(self.catalogue)
        self.primary = primary_models(self.catalogue)
        self._pipeline_getter = pipeline
        self._pipeline: IngestPipeline | None = None
        self._reader: ObservationReader | None = None
        self._outputs: OutputStore | None = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._fitted: dict[tuple[str, str], tuple[int, tuple[str, ...]]] = {}

    @property
    def converser(self) -> Converser:
        if self._converser is None:
            self._converser = self._make_converser()
        return self._converser

    async def pipeline(self) -> IngestPipeline:
        if self._pipeline is None:
            self._pipeline = await self._pipeline_getter()
        return self._pipeline

    async def reader(self) -> ObservationReader:
        if self._reader is None:
            pipe = await self.pipeline()
            self._reader = ObservationReader(pipe.lake, pipe.index)
        return self._reader

    async def outputs(self) -> OutputStore:
        if self._outputs is None:
            pipe = await self.pipeline()
            self._outputs = OutputStore(pipe.lake, pipe.prov)
        return self._outputs

    def models_of(self, kind: DTKind) -> list[Layer4Base]:
        return [m for m in self.catalogue.values() if m.spec.twin is kind]

    def lead_model(self, kind: DTKind) -> Layer4Base | None:
        """The model that creates the first organ instance the twin owns."""
        definition = self.registry.get(kind)
        for anatomy in definition.owns_instances if definition else ():
            if anatomy in self.primary:
                return self.primary[anatomy]
        return None

    async def ensure(self, hdt_id: str, anatomies: Iterable[str]) -> None:
        """Create the person's instances for `anatomies` that do not exist yet."""
        lock = self._locks.setdefault(hdt_id, asyncio.Lock())
        async with lock:
            have = set(self.store.instances(hdt_id))
            missing = [a for a in dict.fromkeys(anatomies) if a not in have]
            if missing:
                await create_person_instances(self.store, hdt_id, self.catalogue,
                                              anatomies=missing)

    async def ensure_twin(self, hdt_id: str, kind: DTKind) -> list[str]:
        definition = self.registry.get(kind)
        owned = list(definition.owns_instances) if definition else []
        await self.ensure(hdt_id, owned)
        return owned

    async def resolve(self, model: Layer4Base, hdt_id: str, *,
                      supplied: Mapping[str, Any] | None = None,
                      as_of: datetime | None = None,
                      store: Any = None) -> ResolvedInputs:
        """Inputs of `model`: supplied values first, then the port's declared source, then the
        person's latest observation of the field named like the port."""
        reader = await self.reader()
        latest = reader.latest(hdt_id, as_of=as_of)
        by_key: dict[str, Reading] = {}
        for code, reading in latest.items():
            by_key[code] = reading
            name = reader.field_name(code)
            if name:
                by_key[name] = reading
        used: list[str] = []
        sources: dict[str, str] = {}

        def lookup(key: str) -> Any:
            reading = by_key.get(key) or by_key.get(reader.canonical(key))
            if reading is None or isinstance(reading.value, str):
                return None
            used.append(reading.record_id)
            sources[reader.field_name(reading.code) or key] = reading.record_id
            return reading.value

        if store is None:
            sources_needed = [src.instance for port in model.spec.inputs
                              if (src := parse(port)) is not None and src.kind == "facet"]
            await self.ensure(hdt_id, sources_needed)
            facets: Any = self.store
        else:
            facets = _TolerantFacets(store)
        values = await resolve_inputs(model, hdt_id, store=facets, fields=lookup,
                                      supplied=supplied)
        for port in model.spec.inputs:
            if port.name not in values and (value := lookup(port.name)) is not None:
                values[port.name] = value
        return ResolvedInputs(values, list(dict.fromkeys(used)), sources)

    async def twin_fields(self, hdt_id: str, kind: DTKind) -> dict[str, dict[str, Any]]:
        """The latest observation of each field of the twin, for the connectors."""
        reader = await self.reader()
        out: dict[str, dict[str, Any]] = {}
        for reading in reader.latest(hdt_id, twin=kind).values():
            name = reader.field_name(reading.code)
            if name is not None and reading.value is not None:
                out[name] = {"value": reading.value, "unit": reading.unit}
        return out

    async def assimilate(self, hdt_id: str, kind: DTKind) -> list[str]:
        """Write the latest observed model outputs of the twin into its instances.

        The write is the assimilation service's, so the owning twin keeps sole write access
        for its own models. An instance whose state already holds the values is not rewritten.
        """
        reader = await self.reader()
        readings = reader.latest(hdt_id)
        written: list[str] = []
        for anatomy in await self.ensure_twin(hdt_id, kind):
            record = await self.store.get(hdt_id, anatomy)
            obs = [r for model in self.contributors.get(anatomy, [])
                   for code in model.spec.obs_map if (r := readings.get(code)) is not None]
            records = [o for r in obs if (o := r.record(hdt_id)) is not None]
            if not records:
                continue
            # The same readings on the same instance revision give the same fit.
            fit_key = (record.revision, tuple(sorted(o.record_id for o in records)))
            if self._fitted.get((hdt_id, anatomy)) == fit_key:
                continue
            update = record
            for model in self.contributors[anatomy]:
                update = await Layer4Base.calibrate(model, update, records)
            if update.state != record.state:
                written_record = await self.store.write(
                    hdt_id, anatomy, writer=ASSIMILATION, state=update.state, params=None,
                    expected_revision=record.revision)
                fit_key = (written_record.revision, fit_key[1])
                written.append(anatomy)
            self._fitted[(hdt_id, anatomy)] = fit_key
        return written

def worst(statuses: Iterable[str]) -> str:
    order = {"normal": 0, "watch": 1, "alert": 2}
    return max(statuses, key=lambda s: order[s], default="normal")

