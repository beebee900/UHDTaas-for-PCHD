"""Waveform store: one Zarr group per person, code and day (design 04, 4.3.2).

`ahdt-waveforms/{hdt_id}/{code}/{date}.zarr` holds `samples` (all segments of the day
appended) and `segments` with one row per appended segment: start time in epoch
milliseconds, offset into `samples`, sample count and sampling period in milliseconds.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import numpy as np
import numpy.typing as npt
import zarr

BUCKET = "ahdt-waveforms"


@dataclass(frozen=True)
class Segment:
    start: datetime
    samples: npt.NDArray[np.float64]
    period_ms: float


class WaveformStore:
    def __init__(self, root: Path) -> None:
        self.root = root
        self._lock = threading.Lock()

    def key(self, hdt_id: str, code: str, day: datetime) -> str:
        return f"{BUCKET}/{hdt_id}/{code}/{day.astimezone(UTC).date().isoformat()}.zarr"

    def _group(self, key: str, mode: Literal["r", "a"]) -> zarr.Group:
        return zarr.open_group(zarr.storage.LocalStore(self.root / key), mode=mode)

    def append(self, hdt_id: str, code: str, start: datetime, samples: list[float],
               period_ms: float) -> str:
        key = self.key(hdt_id, code, start)
        with self._lock:
            group = self._group(key, "a")
            data: Any
            segs: Any
            if "samples" in group:
                data, segs = group["samples"], group["segments"]
            else:
                data = group.create_array("samples", shape=(0,), chunks=(65536,),
                                          dtype="float64")
                segs = group.create_array("segments", shape=(0, 4), chunks=(1024, 4),
                                          dtype="float64")
            offset = data.shape[0]
            data.append(np.asarray(samples, dtype="float64"))
            row = [start.timestamp() * 1000.0, offset, len(samples), period_ms]
            segs.append(np.asarray([row], dtype="float64"))
        return key

    def read(self, hdt_id: str, code: str, day: datetime) -> list[Segment]:
        key = self.key(hdt_id, code, day)
        if not (self.root / key).exists():
            return []
        group = self._group(key, "r")
        data: Any = group["samples"]
        segs: Any = group["segments"]
        out = []
        for start_ms, offset, n, period in np.asarray(segs[:]):
            start = datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=float(start_ms))
            out.append(Segment(start, np.asarray(data[int(offset):int(offset) + int(n)]),
                               float(period)))
        return out
