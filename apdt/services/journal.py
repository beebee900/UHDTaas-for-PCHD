"""Recommendations, bundles and decisions in the per-tenant hash-chained reasoning record."""

from __future__ import annotations

import asyncio

from apdt.records.reasoning import ReasoningRecord
from apdt.records.tables import create_all
from atra import contracts as c
from atra.backends.base import RelationalBackend


class Journal:
    def __init__(self, db: RelationalBackend) -> None:
        self.db = db
        self._ready = False
        self._lock = asyncio.Lock()
        self._records: dict[str, ReasoningRecord] = {}

    async def _record(self, tenant_id: str) -> ReasoningRecord:
        async with self._lock:
            if not self._ready:
                await create_all(self.db)
                self._ready = True
            return self._records.setdefault(tenant_id, ReasoningRecord(self.db, tenant_id))

    async def proposed(self, tenant_id: str, rec: c.Recommendation,
                       bundle: c.ExplanationBundle) -> None:
        record = await self._record(tenant_id)
        await record.recommendation(rec)
        await record.append(episode_id=rec.episode_id or "", hdt_id=rec.hdt_id, kind="bundle",
                            ref_id=bundle.bundle_id, body=bundle.model_dump(mode="json"))

    async def decided(self, tenant_id: str, decision: c.ClinicalDecision, *, episode_id: str,
                      hdt_id: str) -> None:
        await (await self._record(tenant_id)).decision(decision, episode_id=episode_id,
                                                       hdt_id=hdt_id)
