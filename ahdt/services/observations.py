"""Reads of a person's observations from the data lake (design 04, 4.3.2 and 4.7.2).

Every read is a query over the append-only `lake.observations` table. `as_of` limits the
rows to those ingested at or before that time, and the newest version of each reading wins.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ahdt.ingest.fields import FIELD_SYSTEM, FieldIndex
from ahdt.stores.lake import Lake
from atra import contracts as c
from atra.codes import SYSTEMS
from atra.connectors import DTKind

COLUMNS = ("record_id, dt, code_system, code, value_num, value_text, unit, effective_time, "
           "source, quality, consent_tag, provenance_id, version, device_id")


@dataclass(frozen=True)
class Reading:
    record_id: str
    dt: str
    code_system: str
    code: str
    value: float | str | None
    unit: str
    effective_time: datetime
    source: str
    quality: str
    consent_tag: str
    provenance_id: str
    version: int
    device_id: str | None

    def record(self, hdt_id: str) -> c.ObservationRecord | None:
        """The reading as a contract record, or None for a reading without a value."""
        if self.value is None:
            return None
        return c.ObservationRecord(
            record_id=self.record_id, hdt_id=hdt_id, dt=DTKind(self.dt),
            code=c.Code(system=self.code_system, code=self.code), value=self.value,
            unit=self.unit, effective_time=self.effective_time, device_id=self.device_id,
            source=self.source,
            quality=c.Quality(self.quality), consent_tag=self.consent_tag,
            provenance_id=self.provenance_id, version=self.version)


def _reading(row: Mapping[str, Any]) -> Reading:
    num = row["value_num"]
    return Reading(
        record_id=row["record_id"], dt=row["dt"], code_system=row["code_system"],
        code=row["code"], value=float(num) if num is not None else row["value_text"],
        unit=row["unit"], effective_time=row["effective_time"], source=row["source"],
        quality=row["quality"], consent_tag=row["consent_tag"],
        provenance_id=row["provenance_id"], version=int(row["version"]),
        device_id=row["device_id"])


class ObservationReader:
    def __init__(self, lake: Lake, index: FieldIndex) -> None:
        self.lake = lake
        self.index = index

    def canonical(self, code: str) -> str:
        """The stored code for a LOINC, SNOMED CT or MDC code or a field name."""
        for system in (*SYSTEMS.values(), FIELD_SYSTEM):
            ref = self.index.resolve(c.Code(system=system, code=code))
            if ref is not None:
                return ref.code.code
        ref = self.index.by_name(code)
        return ref.code.code if ref is not None else code

    def field_name(self, code: str) -> str | None:
        for system in (*SYSTEMS.values(), FIELD_SYSTEM):
            ref = self.index.resolve(c.Code(system=system, code=code))
            if ref is not None:
                return ref.field.name
        return None

    def read(self, hdt_id: str, codes: Iterable[str] | None = None, *,
             start: datetime | None = None, end: datetime | None = None,
             as_of: datetime | None = None, twin: DTKind | None = None) -> list[Reading]:
        """Accepted readings in time order, one per reading (newest version)."""
        where = ["hdt_id = ?", "ingested_at <= ?", "quality <> 'rejected'"]
        params: list[Any] = [hdt_id, as_of or datetime.now(UTC)]
        if codes is not None:
            wanted = sorted({self.canonical(code) for code in codes})
            where.append("code IN (" + ", ".join("?" for _ in wanted) + ")")
            params += wanted
        if twin is not None:
            where.append("dt = ?")
            params.append(twin.value)
        if start is not None:
            where.append("effective_time >= ?")
            params.append(start)
        if end is not None:
            where.append("effective_time <= ?")
            params.append(end)
        sql = (f"SELECT {COLUMNS} FROM ("
               f" SELECT *, row_number() OVER (PARTITION BY code, effective_time"
               f"   ORDER BY version DESC) AS rn FROM observations WHERE {' AND '.join(where)}"
               f") WHERE rn = 1 ORDER BY effective_time, code")
        return [_reading(r) for r in self.lake.query(sql, params)]

    def latest(self, hdt_id: str, *, as_of: datetime | None = None,
               twin: DTKind | None = None) -> dict[str, Reading]:
        """The newest reading of each stored code."""
        found: dict[str, Reading] = {}
        for r in self.read(hdt_id, as_of=as_of, twin=twin):
            found[r.code] = r
        return found
