"""Data lake: Iceberg tables `lake.observations`, `lake.outputs` and `lake.audit`, daily
partitions by ingestion day (UTC), queried with DuckDB (design 04, 4.3.2).

The p0 catalog is SQLite with a local warehouse directory; p1+ point the same code at the
PostgreSQL catalog and MinIO. Rows are only appended, so the state of a person at any
earlier time is a query over the lake.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import pyarrow as pa
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.exceptions import NamespaceAlreadyExistsError, NoSuchTableError
from pyiceberg.partitioning import PartitionField, PartitionSpec
from pyiceberg.schema import Schema
from pyiceberg.table import Table
from pyiceberg.transforms import IdentityTransform
from pyiceberg.types import (
    DoubleType,
    LongType,
    NestedField,
    StringType,
    TimestamptzType,
)
from sqlalchemy import event

NAMESPACE = "lake"

OBSERVATION_COLUMNS: tuple[tuple[str, Any, bool], ...] = (
    ("record_id", StringType(), True),
    ("hdt_id", StringType(), True),
    ("dt", StringType(), True),
    ("code_system", StringType(), True),
    ("code", StringType(), True),
    ("value_num", DoubleType(), False),
    ("value_text", StringType(), False),
    ("unit", StringType(), True),
    ("effective_time", TimestamptzType(), True),
    ("ingested_at", TimestamptzType(), True),
    ("source", StringType(), True),
    ("quality", StringType(), True),
    ("consent_tag", StringType(), True),
    ("provenance_id", StringType(), True),
    ("version", LongType(), True),
    ("device_id", StringType(), False),
    ("ingested_day", StringType(), True),
)
OUTPUT_COLUMNS: tuple[tuple[str, Any, bool], ...] = (
    ("output_id", StringType(), True),
    ("hdt_id", StringType(), True),
    ("model_id", StringType(), True),
    ("version", StringType(), True),
    ("body", StringType(), True),
    ("ingested_at", TimestamptzType(), True),
    ("ingested_day", StringType(), True),
)
AUDIT_COLUMNS: tuple[tuple[str, Any, bool], ...] = (
    ("seq", LongType(), True),
    ("hash", StringType(), True),
    ("service", StringType(), True),
    ("action", StringType(), True),
    ("target", StringType(), True),
    ("outcome", StringType(), True),
    ("body", StringType(), True),
    ("ingested_at", TimestamptzType(), True),
    ("ingested_day", StringType(), True),
)
TABLES: Mapping[str, tuple[tuple[str, Any, bool], ...]] = {
    "observations": OBSERVATION_COLUMNS, "outputs": OUTPUT_COLUMNS, "audit": AUDIT_COLUMNS}


def _schema(columns: Sequence[tuple[str, Any, bool]]) -> Schema:
    return Schema(*(NestedField(i, name, kind, required=req)
                    for i, (name, kind, req) in enumerate(columns, start=1)))


def _sqlite_wal(dbapi_connection: Any, _record: Any) -> None:
    # Each append commits the catalog; WAL with synchronous=NORMAL keeps that commit from
    # waiting on a disk flush. A process crash loses nothing; a power cut can lose the last commits.
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def _arrow(columns: Sequence[tuple[str, Any, bool]]) -> pa.Schema:
    kinds = {StringType: pa.string(), DoubleType: pa.float64(), LongType: pa.int64(),
             TimestamptzType: pa.timestamp("us", tz="UTC")}
    return pa.schema([pa.field(n, kinds[type(k)], nullable=not req) for n, k, req in columns])


class Lake:
    """Append-only Iceberg tables in one catalog; `tables` defaults to the AHDT lake."""

    def __init__(self, directory: Path,
                 tables: Mapping[str, Sequence[tuple[str, Any, bool]]] = TABLES) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        self.catalog = SqlCatalog(NAMESPACE, uri=f"sqlite:///{directory / 'catalog.db'}",
                                  warehouse=(directory / "warehouse").as_uri())
        event.listen(self.catalog.engine, "connect", _sqlite_wal)
        self.catalog.engine.dispose()
        self._lock = threading.Lock()
        self._scans: dict[str, pa.Table] = {}
        self._duck = duckdb.connect()
        self._registered: dict[str, pa.Table] = {}
        self.tables = tables
        self._tables: dict[str, Table] = {}
        with contextlib.suppress(NamespaceAlreadyExistsError):
            self.catalog.create_namespace(NAMESPACE)
        for name, columns in tables.items():
            self._tables[name] = self._table(name, columns)

    def _table(self, name: str, columns: Sequence[tuple[str, Any, bool]]) -> Table:
        ident = f"{NAMESPACE}.{name}"
        try:
            return self.catalog.load_table(ident)
        except NoSuchTableError:
            schema = _schema(columns)
            source = schema.find_field("ingested_day").field_id
            spec = PartitionSpec(PartitionField(source_id=source, field_id=1000,
                                                transform=IdentityTransform(),
                                                name="ingested_day"))
            return self.catalog.create_table(ident, schema=schema, partition_spec=spec)

    def append(self, table: str, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            return
        stamped = [{**r, "ingested_day": r["ingested_at"].astimezone(UTC).date().isoformat()}
                   for r in rows]
        arrow = pa.Table.from_pylist(stamped, schema=_arrow(self.tables[table]))
        with self._lock:
            tbl = self._tables[table]
            tbl.append(arrow)
            self._tables[table] = self.catalog.load_table(f"{NAMESPACE}.{table}")
            self._scans.pop(table, None)

    def arrow(self, table: str) -> pa.Table:
        """The whole table; the scan is kept until the next append to that table."""
        with self._lock:
            scan = self._scans.get(table)
            if scan is None:
                scan = self._scans[table] = self._tables[table].scan().to_arrow()
            return scan

    def query(self, sql: str, params: Sequence[Any] = (), *, table: str = "observations"
              ) -> list[dict[str, Any]]:
        """Run DuckDB SQL over one lake table, visible to the query under its own name."""
        scan = self.arrow(table)
        with self._lock:
            if self._registered.get(table) is not scan:
                self._duck.register(table, scan)
                self._registered[table] = scan
            cur = self._duck.execute(sql, list(params))
            names = [d[0] for d in cur.description]
            return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]

    def state_at(self, hdt_id: str, as_of: datetime) -> dict[str, dict[str, Any]]:
        """Latest accepted value per code, as known at `as_of`.

        For each code: the newest effective time, then the highest version among the rows
        ingested at or before `as_of`.
        """
        rows = self.query(
            "SELECT code, value_num, value_text, unit, effective_time, version FROM ("
            " SELECT *, row_number() OVER (PARTITION BY code"
            "   ORDER BY effective_time DESC, version DESC) AS rn"
            " FROM observations WHERE hdt_id = ? AND ingested_at <= ? AND quality <> 'rejected'"
            ") WHERE rn = 1", [hdt_id, as_of])
        return {r.pop("code"): r for r in rows}
