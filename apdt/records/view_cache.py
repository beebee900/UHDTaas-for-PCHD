"""AHDT view cache: short-lived copies of AHDT data pulled for a decision (design 05, 5.4.1).

Never the system of record. Every cached item is also noted in the reasoning record
(`kind = ahdt_view`) with its AHDT version and query, so a decision can name what it saw.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from apdt.records.reasoning import ReasoningRecord
from atra.backends.base import CacheBackend

DEFAULT_TTL_S = 300.0


def view_key(tenant_id: str, hdt_id: str, tool: str, args: Mapping[str, Any]) -> str:
    digest = hashlib.sha256(json.dumps(args, sort_keys=True, default=str).encode()).hexdigest()
    return f"apdt:view:{tenant_id}:{hdt_id}:{tool}:{digest[:16]}"


class AhdtViewCache:
    def __init__(self, cache: CacheBackend, reasoning: ReasoningRecord, *,
                 ttl_s: float = DEFAULT_TTL_S) -> None:
        self.cache = cache
        self.reasoning = reasoning
        self.ttl_s = ttl_s

    async def get(self, *, hdt_id: str, episode_id: str, tool: str, args: Mapping[str, Any],
                  fetch: Callable[[], Awaitable[Mapping[str, Any]]]) -> dict[str, Any]:
        """The cached view, or `fetch()` stored for `ttl_s` and noted in the reasoning record."""
        key = view_key(self.reasoning.tenant_id, hdt_id, tool, args)
        hit = await self.cache.get(key)
        if hit is not None:
            return dict(hit)
        data = dict(await fetch())
        await self.cache.set(key, data, ttl_s=self.ttl_s)
        meta = data.get("_meta", {})
        await self.reasoning.append(
            episode_id=episode_id, hdt_id=hdt_id, kind="ahdt_view", ref_id=key[-16:],
            body={"key": key, "tool": tool, "args": dict(args),
                  "ahdt_models": meta.get("models", []),
                  "ttl_s": self.ttl_s})
        return data

    async def invalidate(self, hdt_id: str) -> int:
        return await self.cache.delete_prefix(f"apdt:view:{self.reasoning.tenant_id}:{hdt_id}:")
