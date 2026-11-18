"""Organ instance store with facets, ownership, revisions and forks (design 03, 3.5).

Every shared organ has one instance per person. Only its owning twin, or the 6.2
assimilation service, may write it. Other twins read role-specific facets. Each write
keeps the previous version, so a facet can be read `as_of` an earlier time.
"""

from __future__ import annotations

import asyncio
import copy
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final, Literal

from ahdt.registry import Registry, load_registry
from atra.connectors import DTKind
from atra.contracts import FacetView, InstanceRecord
from atra.ids import instance_id, new_fork_id

ASSIMILATION: Final = "assimilation"
FORK_TTL = timedelta(minutes=15)

type Writer = DTKind | Literal["assimilation"]
type Now = Callable[[], datetime]


class RevisionConflict(ValueError):
    """A write named a revision that is no longer current."""


class ForkExpired(KeyError):
    pass


@dataclass
class _Versions:
    history: list[tuple[datetime, InstanceRecord]] = field(default_factory=list)

    @property
    def current(self) -> InstanceRecord:
        return self.history[-1][1]

    def at(self, when: datetime) -> InstanceRecord | None:
        found = None
        for written, record in self.history:
            if written <= when:
                found = record
        return found


class _Instances:
    """The instance versions of one store or one fork."""

    def __init__(self, registry: Registry, now: Now, fork_id: str | None = None) -> None:
        self.registry = registry
        self.now = now
        self.fork_id = fork_id
        self.data: dict[tuple[str, str], _Versions] = {}
        self.lock = asyncio.Lock()

    def _versions(self, hdt_id: str, anatomy: str) -> _Versions:
        try:
            return self.data[(hdt_id, anatomy)]
        except KeyError:
            raise KeyError(f"no instance {instance_id(hdt_id, anatomy)}") from None

    async def get(self, hdt_id: str, anatomy: str, *,
                  as_of: datetime | None = None) -> InstanceRecord:
        versions = self._versions(hdt_id, anatomy)
        record = versions.current if as_of is None else versions.at(as_of)
        if record is None:
            raise KeyError(f"{instance_id(hdt_id, anatomy)} did not exist at {as_of}")
        return record

    async def get_facet(self, hdt_id: str, anatomy: str, facet: str, *, consumer: DTKind,
                        as_of: datetime | None = None) -> FacetView:
        decl = self.registry.facet(anatomy, facet)
        if decl is None:
            raise KeyError(f"no facet {anatomy}/{facet}")
        if consumer not in decl.consumers:
            raise PermissionError(f"{consumer.value} may not read {anatomy}/{facet}")
        record = await self.get(hdt_id, anatomy, as_of=as_of)
        return FacetView(
            instance_id=record.instance_id, anatomy=anatomy, facet=facet,
            fields={f: record.state.get(f) for f in decl.fields},
            uncertainty={f: record.uncertainty[f] for f in decl.fields
                         if f in record.uncertainty},
            revision=record.revision, fork_id=self.fork_id)

    async def write(self, hdt_id: str, anatomy: str, *, writer: Writer, state: dict[str, Any],
                    params: dict[str, Any] | None, expected_revision: int,
                    uncertainty: dict[str, Any] | None = None) -> InstanceRecord:
        async with self.lock:
            versions = self._versions(hdt_id, anatomy)
            current = versions.current
            if writer != ASSIMILATION and writer is not current.owner_dt:
                name = writer if isinstance(writer, str) else writer.value
                raise PermissionError(f"{name} does not own {current.instance_id}")
            if expected_revision != current.revision:
                raise RevisionConflict(f"{current.instance_id} is at revision "
                                       f"{current.revision}, not {expected_revision}")
            now = self.now()
            update: dict[str, Any] = {"state": {**current.state, **state},
                                      "revision": current.revision + 1}
            if params is not None:
                update["params"] = {**current.params, **params}
            if uncertainty is not None:
                update["uncertainty"] = {**current.uncertainty, **uncertainty}
            if writer == ASSIMILATION:
                update["last_assimilated"] = now
            record = current.model_copy(update=update, deep=True)
            versions.history.append((now, record))
            return record


class ForkHandle:
    """A deep copy of some instances. Writes change the copy only."""

    def __init__(self, store: InstanceStore, instances: _Instances, created: datetime) -> None:
        self._store = store
        self._instances = instances
        self.created = created

    @property
    def fork_id(self) -> str:
        assert self._instances.fork_id is not None
        return self._instances.fork_id

    @property
    def expires(self) -> datetime:
        return self.created + FORK_TTL

    def _live(self) -> _Instances:
        if self._store.now() >= self.expires or self.fork_id not in self._store._forks:
            self._store._forks.pop(self.fork_id, None)
            raise ForkExpired(self.fork_id)
        return self._instances

    async def get(self, hdt_id: str, anatomy: str) -> InstanceRecord:
        return await self._live().get(hdt_id, anatomy)

    async def get_facet(self, hdt_id: str, anatomy: str, facet: str, *, consumer: DTKind,
                        as_of: datetime | None = None) -> FacetView:
        return await self._live().get_facet(hdt_id, anatomy, facet, consumer=consumer,
                                            as_of=as_of)

    async def write(self, hdt_id: str, anatomy: str, *, writer: Writer, state: dict[str, Any],
                    params: dict[str, Any] | None, expected_revision: int,
                    uncertainty: dict[str, Any] | None = None) -> InstanceRecord:
        return await self._live().write(hdt_id, anatomy, writer=writer, state=state,
                                        params=params, expected_revision=expected_revision,
                                        uncertainty=uncertainty)


class InstanceStore:
    """In-process instance store (profile p0)."""

    def __init__(self, registry: Registry | None = None, *, now: Now | None = None) -> None:
        self.registry = registry or load_registry()
        self.now: Now = now or (lambda: datetime.now(UTC))
        self._main = _Instances(self.registry, self.now)
        self._forks: dict[str, ForkHandle] = {}

    async def create(self, record: InstanceRecord) -> InstanceRecord:
        hdt_id = "-".join(record.instance_id.split("-")[1:3])
        owner = self.registry.owner_of(record.anatomy)
        if owner is not record.owner_dt:
            raise PermissionError(f"{record.anatomy} is owned by "
                                  f"{owner.value if owner else 'no twin'}")
        async with self._main.lock:
            key = (hdt_id, record.anatomy)
            if key in self._main.data:
                raise ValueError(f"{record.instance_id} exists")
            self._main.data[key] = _Versions([(self.now(), record.model_copy(deep=True))])
        return record

    def instances(self, hdt_id: str) -> list[str]:
        return sorted(a for h, a in self._main.data if h == hdt_id)

    async def get(self, hdt_id: str, anatomy: str, *,
                  as_of: datetime | None = None) -> InstanceRecord:
        return await self._main.get(hdt_id, anatomy, as_of=as_of)

    async def get_facet(self, hdt_id: str, anatomy: str, facet: str, *, consumer: DTKind,
                        as_of: datetime | None = None) -> FacetView:
        return await self._main.get_facet(hdt_id, anatomy, facet, consumer=consumer,
                                          as_of=as_of)

    async def write(self, hdt_id: str, anatomy: str, *, writer: Writer, state: dict[str, Any],
                    params: dict[str, Any] | None, expected_revision: int,
                    uncertainty: dict[str, Any] | None = None) -> InstanceRecord:
        return await self._main.write(hdt_id, anatomy, writer=writer, state=state,
                                      params=params, expected_revision=expected_revision,
                                      uncertainty=uncertainty)

    async def fork(self, hdt_id: str, anatomies: Sequence[str]) -> ForkHandle:
        self._expire()
        copy_ = _Instances(self.registry, self.now, new_fork_id())
        for anatomy in anatomies:
            record = await self._main.get(hdt_id, anatomy)
            copy_.data[(hdt_id, anatomy)] = _Versions([(self.now(), copy.deepcopy(record))])
        handle = ForkHandle(self, copy_, self.now())
        self._forks[handle.fork_id] = handle
        return handle

    async def release(self, fork_id: str) -> None:
        self._forks.pop(fork_id, None)

    def forks(self) -> Mapping[str, ForkHandle]:
        self._expire()
        return dict(self._forks)

    def _expire(self) -> None:
        now = self.now()
        for fid in [f for f, h in self._forks.items() if now >= h.expires]:
            del self._forks[fid]
