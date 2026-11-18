"""Clinical reasoning record: differentials, cited evidence, AHDT view keys, decisions and
override reasons, in an append-only table with a per-tenant hash chain (design 03, 3.11)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select

from apdt.records.tables import reasoning_log
from atra.backends.base import RelationalBackend
from atra.contracts import ClinicalDecision, Recommendation
from atra.provenance import GENESIS_HASH, ChainBroken, record_hash

type ReasoningKind = Literal["differential", "evidence", "ahdt_view", "recommendation",
                             "decision", "bundle", "note"]


class ReasoningRecord:
    def __init__(self, db: RelationalBackend, tenant_id: str) -> None:
        self.db = db
        self.tenant_id = tenant_id
        self._lock = asyncio.Lock()

    async def append(self, *, episode_id: str, hdt_id: str, kind: ReasoningKind, ref_id: str,
                     body: Mapping[str, Any], t: datetime | None = None) -> dict[str, Any]:
        async with self._lock, self.db.engine().begin() as conn:
            last = (await conn.execute(
                select(reasoning_log.c.seq, reasoning_log.c.hash)
                .where(reasoning_log.c.tenant_id == self.tenant_id)
                .order_by(reasoning_log.c.seq.desc()).limit(1))).first()
            row: dict[str, Any] = {
                "tenant_id": self.tenant_id, "seq": 0 if last is None else last.seq + 1,
                "prev_hash": GENESIS_HASH if last is None else last.hash,
                "episode_id": episode_id, "hdt_id": hdt_id, "kind": kind, "ref_id": ref_id,
                "body": dict(body), "t": (t or datetime.now(UTC)).isoformat()}
            row["hash"] = record_hash(row)
            await conn.execute(reasoning_log.insert().values(
                {**row, "t": datetime.fromisoformat(row["t"])}))
            return row

    async def recommendation(self, rec: Recommendation) -> dict[str, Any]:
        if rec.episode_id is None:
            raise ValueError("a recommendation in the reasoning record needs an episode")
        return await self.append(episode_id=rec.episode_id, hdt_id=rec.hdt_id,
                                 kind="recommendation", ref_id=rec.recommendation_id,
                                 body=rec.model_dump(mode="json"))

    async def decision(self, decision: ClinicalDecision, *, episode_id: str,
                       hdt_id: str) -> dict[str, Any]:
        if decision.decision in ("edit", "reject") and not decision.override_reason:
            raise ValueError("an override needs a reason")
        return await self.append(episode_id=episode_id, hdt_id=hdt_id, kind="decision",
                                 ref_id=decision.decision_id, body=decision.model_dump(mode="json"))

    async def entries(self, *, episode_id: str | None = None,
                      kind: ReasoningKind | None = None) -> list[dict[str, Any]]:
        q = select(reasoning_log).where(reasoning_log.c.tenant_id == self.tenant_id)
        if episode_id is not None:
            q = q.where(reasoning_log.c.episode_id == episode_id)
        if kind is not None:
            q = q.where(reasoning_log.c.kind == kind)
        async with self.db.engine().connect() as conn:
            rows = (await conn.execute(q.order_by(reasoning_log.c.seq))).mappings().all()
        return [_as_record(r) for r in rows]

    async def count(self) -> int:
        async with self.db.engine().connect() as conn:
            return int((await conn.execute(select(func.count()).select_from(reasoning_log)
                        .where(reasoning_log.c.tenant_id == self.tenant_id))).scalar_one())

    async def verify(self) -> int:
        """Recompute every hash and link of this tenant's chain. Returns the records checked."""
        prev = GENESIS_HASH
        rows = await self.entries()
        for i, row in enumerate(rows):
            if row["seq"] != i or row["prev_hash"] != prev or record_hash(row) != row["hash"]:
                raise ChainBroken(f"reasoning chain of {self.tenant_id} breaks at seq {row['seq']}")
            prev = row["hash"]
        return len(rows)


def _as_record(row: Mapping[str, Any]) -> dict[str, Any]:
    out = dict(row)
    t = out["t"]
    if t.tzinfo is None:
        t = t.replace(tzinfo=UTC)
    out["t"] = t.isoformat()
    return out
