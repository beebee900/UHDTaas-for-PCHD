"""Simulation clock and hybrid logical clock (design 02, section 2.8)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import total_ordering

DEFAULT_SPEED = 240.0

type WallClockMs = Callable[[], int]


class SimClock:
    """Maps wall time to scenario time at a fixed speed factor.

    With the default factor of 240, a 72-hour episode runs in 18 minutes. A manual clock
    (`manual=True`) only moves when `advance` is called, which makes tests deterministic.
    """

    def __init__(self, *, speed: float = DEFAULT_SPEED, start: datetime | None = None,
                 manual: bool = False) -> None:
        if speed <= 0:
            raise ValueError("speed must be positive")
        self.speed = speed
        self.start = start or datetime.now(UTC)
        self.manual = manual
        self._wall0 = time.monotonic()
        self._manual_s = 0.0

    def sim_time(self) -> float:
        """Seconds of scenario time since the start."""
        if self.manual:
            return self._manual_s
        return (time.monotonic() - self._wall0) * self.speed

    def now(self) -> datetime:
        """The scenario's current date-time."""
        return self.start + timedelta(seconds=self.sim_time())

    def advance(self, seconds: float) -> float:
        if not self.manual:
            raise RuntimeError("advance() needs a manual clock")
        if seconds < 0:
            raise ValueError("a clock cannot go back")
        self._manual_s += seconds
        return self._manual_s

    def wall_seconds_for(self, sim_seconds: float) -> float:
        return sim_seconds / self.speed


@total_ordering
@dataclass(frozen=True)
class HLCStamp:
    physical_ms: int
    counter: int
    node: str

    def __str__(self) -> str:
        return f"{self.physical_ms}.{self.counter}.{self.node}"

    @classmethod
    def parse(cls, text: str) -> HLCStamp:
        physical, counter, node = text.split(".", 2)
        return cls(int(physical), int(counter), node)

    def _key(self) -> tuple[int, int, str]:
        return (self.physical_ms, self.counter, self.node)

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, HLCStamp):
            return NotImplemented
        return self._key() < other._key()


class HybridLogicalClock:
    """Kulkarni et al. (2014) hybrid logical clock.

    Stamps stay close to physical time and still order every send before its receive,
    so receivers can reorder messages from twins with skewed clocks.
    """

    def __init__(self, node: str, *, wall_ms: WallClockMs | None = None) -> None:
        if "." in node:
            raise ValueError("node names cannot contain '.'")
        self.node = node
        self._wall_ms = wall_ms or (lambda: time.time_ns() // 1_000_000)
        self._last = HLCStamp(0, 0, node)
        self._lock = threading.Lock()

    def now(self) -> HLCStamp:
        """Stamp for a local or send event."""
        with self._lock:
            pt = self._wall_ms()
            if pt > self._last.physical_ms:
                self._last = HLCStamp(pt, 0, self.node)
            else:
                self._last = HLCStamp(self._last.physical_ms, self._last.counter + 1, self.node)
            return self._last

    def update(self, remote: HLCStamp | str) -> HLCStamp:
        """Stamp for a receive event that carried `remote`."""
        r = HLCStamp.parse(remote) if isinstance(remote, str) else remote
        with self._lock:
            pt = self._wall_ms()
            physical = max(pt, self._last.physical_ms, r.physical_ms)
            if physical == self._last.physical_ms == r.physical_ms:
                counter = max(self._last.counter, r.counter) + 1
            elif physical == self._last.physical_ms:
                counter = self._last.counter + 1
            elif physical == r.physical_ms:
                counter = r.counter + 1
            else:
                counter = 0
            self._last = HLCStamp(physical, counter, self.node)
            return self._last

