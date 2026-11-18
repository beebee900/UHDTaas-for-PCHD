"""The 17 twin definitions and the shared-organ facets (design 03, 3.2 and 3.5)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from atra.connectors import DTKind
from atra.contracts import TwinDefinition

REGISTRY_DIR = Path(__file__).resolve().parent


class FacetDecl(BaseModel):
    model_config = ConfigDict(extra="forbid")

    instance: str
    facet: str
    fields: list[str]
    consumers: list[DTKind]


@dataclass(frozen=True)
class Registry:
    twins: Mapping[DTKind, TwinDefinition]
    facets: tuple[FacetDecl, ...]

    def get(self, kind: DTKind) -> TwinDefinition | None:
        return self.twins.get(kind)

    def owner_of(self, instance: str) -> DTKind | None:
        for kind, twin in self.twins.items():
            if instance in twin.owns_instances:
                return kind
        return None

    def facet(self, instance: str, facet: str) -> FacetDecl | None:
        return next((f for f in self.facets if f.instance == instance and f.facet == facet), None)

    def problems(self) -> list[str]:
        """Consistency errors across twin files and facets; empty when the registry is sound."""
        errors: list[str] = []
        if set(self.twins) != {k for k in DTKind if k.is_ahdt_member}:
            errors.append("the registry must define exactly the 17 AHDT twins")
        owners: dict[str, DTKind] = {}
        for kind, twin in self.twins.items():
            for inst in twin.owns_instances:
                if inst in owners:
                    errors.append(f"{inst} is owned by both {owners[inst].value} and {kind.value}")
                owners[inst] = kind
            for read in twin.reads_facets:
                decl = self.facet(read.instance, read.facet)
                if decl is None:
                    errors.append(f"{kind.value} reads undeclared facet "
                                  f"{read.instance}/{read.facet}")
                elif kind not in decl.consumers:
                    errors.append(f"{kind.value} is not a consumer of {read.instance}/{read.facet}")
            for goal in twin.standing_goals:
                model = goal.check.params.get("model")
                if isinstance(model, str) and model not in twin.models:
                    errors.append(f"goal {goal.id} uses model {model} that {kind.value} lacks")
        for decl in self.facets:
            if decl.instance not in owners:
                errors.append(f"facet {decl.instance}/{decl.facet} has no owning twin")
        return errors


def _load_yaml(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@lru_cache(maxsize=1)
def load_registry(directory: Path = REGISTRY_DIR) -> Registry:
    twins = {}
    for path in sorted(directory.glob("*.yaml")):
        if path.name == "facets.yaml":
            continue
        twin = TwinDefinition.model_validate(_load_yaml(path))
        if path.stem != twin.kind.value:
            raise ValueError(f"{path.name} defines {twin.kind.value}")
        twins[twin.kind] = twin
    facets = tuple(FacetDecl.model_validate(f) for f in _load_yaml(directory / "facets.yaml"))
    return Registry(twins, facets)


def iter_kb_refs(obj: Any) -> Iterator[str]:
    """Every `{"kb": "<entry id>"}` reference inside a nested structure."""
    if isinstance(obj, Mapping):
        if set(obj) == {"kb"} and isinstance(obj["kb"], str):
            yield obj["kb"]
        else:
            for value in obj.values():
                yield from iter_kb_refs(value)
    elif isinstance(obj, list | tuple):
        for value in obj:
            yield from iter_kb_refs(value)
