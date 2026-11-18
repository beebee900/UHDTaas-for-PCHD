"""Phone media and app-use logs (design 04, 4.1.1).

- Microphone clips arrive as 16-bit PCM WAV. `cough_rate` is the edge pre-screen used until the
  6.4 perceive service classifies coughs: it counts bursts whose short-time energy rises above
  `COUGH_DB` dB over the clip's median frame energy, merging bursts closer than
  `COUGH_GAP_S`, and scales the count to events per hour.
- Camera photos are stored for 6.4 perceive and give no reading at the edge.
- App-use logs are lists of Android `UsageStats` records with the getter names of the
  Android API reference (`packageName`, `totalTimeInForeground` in ms, `firstTimeStamp`,
  `lastTimeStamp` in ms since the epoch). Screen time is the foreground total in minutes.
"""

from __future__ import annotations

import io
import json
import wave
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

import numpy as np
import numpy.typing as npt

from edge.devices.decode.observations import CodedReading, field_reading

FRAME_S = 0.02
COUGH_DB = 20.0
COUGH_GAP_S = 0.3


class MediaError(ValueError):
    pass


def read_wav(data: bytes) -> tuple[npt.NDArray[np.float64], int]:
    with wave.open(io.BytesIO(data)) as w:
        if w.getsampwidth() != 2:
            raise MediaError("clips are 16-bit PCM")
        frames = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2")
        channels, rate = w.getnchannels(), w.getframerate()
    return frames.reshape(-1, channels)[:, 0].astype(float), rate


def write_wav(samples: npt.NDArray[np.float64], rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(np.clip(samples, -32768, 32767).astype("<i2").tobytes())
    return buf.getvalue()


def cough_bursts(samples: npt.NDArray[np.float64], rate: int) -> int:
    n = int(FRAME_S * rate)
    frames = samples[: len(samples) // n * n].reshape(-1, n)
    energy = 10 * np.log10((frames ** 2).mean(axis=1) + 1e-9)
    loud = energy > np.median(energy) + COUGH_DB
    gap = int(COUGH_GAP_S / FRAME_S)
    bursts, last = 0, -gap - 1
    for i in np.flatnonzero(loud):
        if i - last > gap:
            bursts += 1
        last = int(i)
    return bursts


def cough_rate(clip: bytes, time: datetime) -> list[CodedReading]:
    samples, rate = read_wav(clip)
    hours = len(samples) / rate / 3600.0
    return field_reading("cough_events", cough_bursts(samples, rate) / hours, "/h", time)


def screen_time(log: bytes | Sequence[Mapping[str, Any]]) -> list[CodedReading]:
    records = json.loads(log) if isinstance(log, bytes) else log
    if not records:
        return []
    total_ms = sum(int(r["totalTimeInForeground"]) for r in records)
    end = max(int(r["lastTimeStamp"]) for r in records)
    return field_reading("screen_time", total_ms / 60000.0, "min",
                         datetime.fromtimestamp(end / 1000, UTC))
