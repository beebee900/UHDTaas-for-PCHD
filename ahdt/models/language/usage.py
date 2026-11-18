"""Token and latency accounting for language-model calls."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated: bool = False
    """True when the backend reported no counts and the numbers are estimates."""

    @property
    def total(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(frozen=True)
class UsageRecord:
    backend: str
    model: str
    locale: str
    usage: TokenUsage
    latency_s: float
    ok: bool = True


@dataclass
class UsageLedger:
    """Thread-safe list of calls with totals per backend."""

    records: list[UsageRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, record: UsageRecord) -> None:
        with self._lock:
            self.records.append(record)

    def totals(self) -> dict[str, dict[str, float]]:
        out: dict[str, dict[str, float]] = {}
        with self._lock:
            for r in self.records:
                row = out.setdefault(r.backend, {"calls": 0, "failures": 0, "prompt_tokens": 0,
                                                 "completion_tokens": 0, "latency_s": 0.0})
                row["calls"] += 1
                row["failures"] += 0 if r.ok else 1
                row["prompt_tokens"] += r.usage.prompt_tokens
                row["completion_tokens"] += r.usage.completion_tokens
                row["latency_s"] += r.latency_s
        return out
