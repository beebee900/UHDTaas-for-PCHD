"""Relational tables of the AHDT Layer 3.1 stores, portable across SQLite (p0) and
PostgreSQL (p1+). The identity table is the only place a direct identifier is kept."""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Integer, MetaData, String, Table, Text

from atra.backends.base import RelationalBackend

metadata = MetaData()

identity = Table(
    "ingest_identity", metadata,
    Column("system", String(128), primary_key=True),
    Column("value", String(128), primary_key=True),
    Column("hdt_id", String(32), nullable=False, index=True),
)
rejected = Table(
    "ingest_rejected", metadata,
    Column("record_id", String(64), primary_key=True),
    Column("hdt_id", String(32), index=True),
    Column("code", String(160), nullable=False),
    Column("value", JSON),
    Column("unit", String(64)),
    Column("effective_time", DateTime(timezone=True)),
    Column("reason", Text, nullable=False),
    Column("stage", String(16), nullable=False),
    Column("received_at", DateTime(timezone=True), nullable=False),
)
seen = Table(
    "ingest_seen", metadata,
    Column("key", String(160), primary_key=True),
    Column("record_id", String(64), nullable=False),
    Column("version", Integer, nullable=False),
)


async def create_all(db: RelationalBackend) -> None:
    async with db.engine().begin() as conn:
        await conn.run_sync(metadata.create_all)
