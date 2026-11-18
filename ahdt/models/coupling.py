"""Coupling hooks: where each model input comes from (design 08, WP14a step 5).

An input port names its source as one of:

- `facet:<instance>/<facet>#<field>`: a facet of a shared organ instance, read with the
  model's twin as the consumer, so the facet rules of the instance store apply;
- `connector:<Connector>#<field>`: a field of the latest payload of an incoming connector;
- `model:<model_id>#<output>`: an output of another model of the same twin;
- `field:<code or field name>`: the person's latest observation;
- `input:<kind>`: supplied by the caller (scenario, demographics, drug, condition).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from ahdt.models.base import Layer4Base, Port
from ahdt.models.organs.store import InstanceStore

KINDS = ("facet", "connector", "model", "field", "input")

type Lookup = Callable[[str], Any]


@dataclass(frozen=True)
class Source:
    kind: str
    target: str
    item: str | None

    @property
    def instance(self) -> str:
        return self.target.rsplit("/", 1)[0]

    @property
    def facet(self) -> str:
        return self.target.rsplit("/", 1)[1]


def parse(port: Port) -> Source | None:
    """The parsed source of a port, or None for a port the caller always supplies."""
    if port.from_ is None:
        return None
    kind, _, rest = port.from_.partition(":")
    if kind not in KINDS or not rest:
        raise ValueError(f"{port.name}: unknown source '{port.from_}'")
    target, _, item = rest.partition("#")
    if kind in ("facet", "connector", "model") and not item:
        item = port.name
    return Source(kind, target, item or None)


async def resolve_inputs(model: Layer4Base, hdt_id: str, *, store: InstanceStore | None = None,
                         connectors: Mapping[str, Mapping[str, Any]] | None = None,
                         outputs: Mapping[str, Mapping[str, Any]] | None = None,
                         fields: Lookup | None = None,
                         supplied: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Values for every input port that has a source available. Supplied values win."""
    values: dict[str, Any] = {}
    for port in model.spec.inputs:
        source = parse(port)
        value: Any = None
        if source is None or source.kind == "input":
            pass
        elif source.kind == "facet" and store is not None:
            view = await store.get_facet(hdt_id, source.instance, source.facet,
                                         consumer=model.spec.twin)
            value = view.fields.get(source.item or port.name)
        elif source.kind == "connector" and connectors is not None:
            value = connectors.get(source.target, {}).get(source.item or port.name)
        elif source.kind == "model" and outputs is not None:
            value = outputs.get(source.target, {}).get(source.item or port.name)
        elif source.kind == "field" and fields is not None:
            value = fields(source.target)
        if value is not None:
            values[port.name] = value
    values.update(supplied or {})
    return values
