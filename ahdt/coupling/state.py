"""Source state of one twin for its connectors, read from the WP14a instance store."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ahdt.models.base import Layer4Base
from ahdt.models.organs.store import InstanceStore
from ahdt.registry import Registry, load_registry
from atra.connectors import DTKind

type FieldsFn = Callable[[str, DTKind], Awaitable[Mapping[str, Mapping[str, Any]]]]
type ContextFn = Callable[[str], Mapping[str, Any]]
type StateFn = Callable[[], Awaitable[dict[str, Any]]]


def output_units(catalogue: Mapping[str, Layer4Base]) -> dict[DTKind, dict[str, str]]:
    """UCUM unit of every model output, per twin (the first model to name it wins)."""
    units: dict[DTKind, dict[str, str]] = {}
    for model in catalogue.values():
        own = units.setdefault(model.spec.twin, {})
        for port in model.spec.outputs:
            own.setdefault(port.name, port.unit)
    return units


class TwinStateProvider:
    """Builds the source-state mapping of `ahdt.coupling.mapping` for any twin of an HDT.

    `state` merges the states of the instances the twin owns, `units` comes from the model
    output ports, `fields` from the latest-observation lookup and `context` from the
    person's context lookup (demographics, recorded conditions).
    """

    def __init__(self, store: InstanceStore, *, units: Mapping[DTKind, Mapping[str, str]],
                 registry: Registry | None = None, fields: FieldsFn | None = None,
                 context: ContextFn | None = None) -> None:
        self.store = store
        self.units = units
        self.registry = registry or store.registry or load_registry()
        self.fields = fields
        self.context = context

    async def state(self, hdt_id: str, kind: DTKind) -> dict[str, Any]:
        definition = self.registry.get(kind)
        merged: dict[str, Any] = {}
        models: dict[str, str] = {}
        for anatomy in definition.owns_instances if definition else ():
            try:
                record = await self.store.get(hdt_id, anatomy)
            except KeyError:
                continue
            for key, value in record.state.items():
                merged.setdefault(key, value)
            models[anatomy] = f"{record.model_id}@{record.version}"
        units = self.units.get(kind, {})
        return {
            "state": merged,
            "units": {k: units[k] for k in merged if k in units},
            "fields": dict(await self.fields(hdt_id, kind)) if self.fields else {},
            "context": dict(self.context(hdt_id)) if self.context else {},
            "_models": models,
        }

    def provider(self, hdt_id: str, kind: DTKind) -> StateFn:
        """The `state_provider` of a connector whose source is `kind`."""

        async def read() -> dict[str, Any]:
            return await self.state(hdt_id, kind)

        return read
