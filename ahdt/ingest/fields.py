"""Which twin owns an incoming code, and in which unit it is stored (design 03, 3.2).

Every field of a twin definition is reachable by its LOINC, SNOMED CT and MDC codes and by
its field name under `FIELD_SYSTEM`, for fields that have no standard code.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache

from ahdt.registry import Registry, load_registry
from atra.codes import SYSTEMS
from atra.connectors import DTKind
from atra.contracts import Code, FieldDefinition

FIELD_SYSTEM = "urn:atra:field"


@dataclass(frozen=True)
class FieldRef:
    twin: DTKind
    field: FieldDefinition

    @property
    def code(self) -> Code:
        """The canonical code: LOINC, else SNOMED CT, else MDC, else the field name."""
        f = self.field
        if f.loinc:
            return Code(system=SYSTEMS["loinc"], code=f.loinc)
        if f.snomed:
            return Code(system=SYSTEMS["snomed"], code=f.snomed)
        if f.mdc:
            return Code(system=SYSTEMS["mdc"], code=f.mdc)
        return Code(system=FIELD_SYSTEM, code=f.name)

    @property
    def alt_codes(self) -> list[Code]:
        f = self.field
        out = [Code(system=SYSTEMS[s], code=v)
               for s, v in (("snomed", f.snomed), ("mdc", f.mdc)) if v]
        return [c for c in out if c != self.code]


class FieldIndex:
    def __init__(self, registry: Registry) -> None:
        self._by_code: dict[tuple[str, str], FieldRef] = {}
        self._by_name: dict[str, FieldRef] = {}
        for kind, twin in registry.twins.items():
            for f in twin.fields:
                ref = FieldRef(kind, f)
                self._by_name.setdefault(f.name, ref)
                for system, value in (("loinc", f.loinc), ("snomed", f.snomed), ("mdc", f.mdc)):
                    if value:
                        self._by_code.setdefault((SYSTEMS[system], value), ref)
                self._by_code.setdefault((FIELD_SYSTEM, f.name), ref)

    def resolve(self, code: Code) -> FieldRef | None:
        return self._by_code.get((SYSTEMS.get(code.system, code.system), code.code))

    def by_name(self, name: str) -> FieldRef | None:
        return self._by_name.get(name)

    def fields_of(self, twin: DTKind) -> Mapping[str, FieldRef]:
        return {n: r for n, r in self._by_name.items() if r.twin is twin}


@lru_cache(maxsize=1)
def field_index() -> FieldIndex:
    return FieldIndex(load_registry())
