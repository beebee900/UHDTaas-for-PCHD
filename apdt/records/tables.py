"""Relational tables of the APDT stores. Portable across SQLite (p0) and PostgreSQL (p1+);
the design's `agency`, `reasoning` and `activity` schemas are table-name prefixes here."""

from __future__ import annotations

from sqlalchemy import JSON, Column, DateTime, Float, Integer, MetaData, String, Table, Text

from atra.backends.base import RelationalBackend

metadata = MetaData()

agency_weights = Table(
    "agency_weights", metadata,
    Column("tenant_id", String(32), primary_key=True),
    Column("hdt_id", String(32), primary_key=True),
    Column("criterion", String(64), primary_key=True),
    Column("weight", Float, nullable=False),
    Column("method", String(32), nullable=False),
    Column("recorded_at", DateTime(timezone=True), nullable=False),
)
agency_questions = Table(
    "agency_questions", metadata,
    Column("question_id", String(48), primary_key=True),
    Column("tenant_id", String(32), nullable=False, index=True),
    Column("hdt_id", String(32), nullable=False, index=True),
    Column("episode_id", String(32)),
    Column("channel", String(16), nullable=False),
    Column("text", Text, nullable=False),
    Column("answer", Text),
    Column("asked_at", DateTime(timezone=True), nullable=False),
    Column("answered_at", DateTime(timezone=True)),
)
reasoning_log = Table(
    "reasoning_log", metadata,
    Column("tenant_id", String(32), primary_key=True),
    Column("seq", Integer, primary_key=True),
    Column("prev_hash", String(64), nullable=False),
    Column("hash", String(64), nullable=False),
    Column("episode_id", String(32), nullable=False, index=True),
    Column("hdt_id", String(32), nullable=False),
    Column("kind", String(32), nullable=False),
    Column("ref_id", String(64), nullable=False, index=True),
    Column("body", JSON, nullable=False),
    Column("t", DateTime(timezone=True), nullable=False),
)
activity = Table(
    "activity", metadata,
    Column("activity_id", String(48), primary_key=True),
    Column("tenant_id", String(32), nullable=False, index=True),
    Column("episode_id", String(32), index=True),
    Column("hdt_id", String(32)),
    Column("kind", String(16), nullable=False),
    Column("status", String(16), nullable=False),
    Column("to_role", String(32)),
    Column("to_id", String(64)),
    Column("body", JSON, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("due_by", DateTime(timezone=True)),
    Column("closed_at", DateTime(timezone=True)),
    Column("closed_by", String(64)),
)


async def create_all(db: RelationalBackend) -> None:
    async with db.engine().begin() as conn:
        await conn.run_sync(metadata.create_all)
