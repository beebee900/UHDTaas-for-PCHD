"""Shared simulator machinery: truth streams, seeding and the simulated clock.

A `TruthStream` holds one person's true physiology per twin field, in the field's unit, as
(seconds from `start`, value) samples. The generators that build it live outside the services;
simulators only read it. A simulator samples the stream at its own schedule, adds its
measurement noise (none by default, so a noiseless run reproduces the truth within the wire
format's resolution) and writes wire bytes to a transport.

Time is compressed: a simulator emits a whole run at once, and the device timestamps follow
the simulated clock (`start` + offset), not the wall clock.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np


@dataclass(frozen=True)
class TruthStream:
    hdt_id: str
    start: datetime
    series: Mapping[str, Sequence[tuple[float, float]]]
    documents: Mapping[str, Any] = field(default_factory=dict)
    """Non-series truth: lab panels, genotypes, questionnaire answers."""

    def has(self, name: str) -> bool:
        return bool(self.series.get(name))

    def times(self, name: str) -> list[float]:
        return [t for t, _ in self.series[name]]

    def at(self, name: str, t_s: float) -> float:
        """The value at `t_s`, linear between samples and held beyond the ends."""
        points = self.series[name]
        ts = [t for t, _ in points]
        vs = [v for _, v in points]
        return float(np.interp(t_s, ts, vs))

    def when(self, t_s: float) -> datetime:
        return self.start + timedelta(seconds=t_s)


def seed_of(*parts: str) -> int:
    return int.from_bytes(hashlib.sha256("|".join(parts).encode()).digest()[:8], "big")


@dataclass
class Simulator:
    device_id: str
    stream: TruthStream
    noise: Mapping[str, float] = field(default_factory=dict)
    """Measurement noise SD per field, in the field's unit."""

    def __post_init__(self) -> None:
        self.rng = np.random.default_rng(seed_of(self.stream.hdt_id, self.device_id))

    @property
    def hdt_id(self) -> str:
        return self.stream.hdt_id

    def measure(self, name: str, t_s: float) -> float:
        value = self.stream.at(name, t_s)
        sd = self.noise.get(name, 0.0)
        return value + float(self.rng.normal(0.0, sd)) if sd else value

    def schedule(self, name: str, every_s: float | None = None) -> list[float]:
        """The truth's own sample times, or a regular grid across its span."""
        ts = self.stream.times(name)
        if every_s is None:
            return ts
        return list(np.arange(ts[0], ts[-1] + 1e-9, every_s))

    def topic(self, device_class: str) -> str:
        return f"dev/{self.hdt_id}/{self.device_id}/{device_class}"
