"""Edge pre-processing (design 04, 4.2.1 tier 2) of the gateway's ingestion payloads.

- ECG waveforms: band-pass Butterworth filter and R-peak detection with NeuroKit2. The
  filtered waveform replaces the raw one, and each strip gives a derived heart rate (LOINC
  8867-4) and RMSSD (`hrv_rmssd`) from its R-R intervals.
- SpO2: readings outside the plausibility bounds of `kb/plausibility.yaml` are sensor dropouts
  (finger out, motion) and are removed before anything leaves the edge.
- Feature windows: scalar readings are summarised per person, code and window (mean, min,
  max, count). The windows feed the edge models and, on a `2g` link, replace the raw stream.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Any

import numpy as np
import numpy.typing as npt

from ahdt.ingest.validate import plausibility_bounds
from atra.codes import SYSTEMS
from edge.devices.decode.observations import FIELD_SYSTEM, HEART_RATE, SPO2

ECG_CODE = "MDC_ECG_ELEC_POTL_II"
ECG_BAND_HZ = (0.5, 40.0)
ECG_FILTER_ORDER = 5
MIN_R_PEAKS = 3
DROPOUT_FIELDS = {SPO2: "spo2"}
LOINC = SYSTEMS["loinc"]


@dataclass(frozen=True)
class FeatureWindow:
    hdt_id: str
    code: Mapping[str, Any]
    unit: str
    start: datetime
    window_s: float
    mean: float
    min: float
    max: float
    members: tuple[Mapping[str, Any], ...]

    @property
    def n(self) -> int:
        return len(self.members)

    def payload(self) -> dict[str, Any]:
        """The window as one reading: a single member as it is, otherwise the mean at the
        window start as a derived reading."""
        if self.n == 1:
            return dict(self.members[0])
        devices = {m.get("device_id") for m in self.members}
        return {"code": dict(self.code), "alt_codes": [], "value": self.mean,
                "unit": self.unit, "effective_time": self.start.isoformat(),
                "source": "derived", "hdt_id": self.hdt_id,
                "device_id": devices.pop() if len(devices) == 1 else None, "sim_time": None}


@dataclass
class Preprocessed:
    payloads: list[dict[str, Any]] = field(default_factory=list)
    features: list[FeatureWindow] = field(default_factory=list)
    dropouts: int = 0


@dataclass(frozen=True)
class EcgStrip:
    cleaned: npt.NDArray[np.float64]
    r_peaks: npt.NDArray[np.int_]
    fs: float

    @property
    def rr_ms(self) -> npt.NDArray[np.float64]:
        out: npt.NDArray[np.float64] = np.diff(self.r_peaks) / self.fs * 1000.0
        return out

    @property
    def heart_rate(self) -> float | None:
        rr = self.rr_ms
        return float(60_000.0 / rr.mean()) if len(self.r_peaks) >= MIN_R_PEAKS else None

    @property
    def rmssd(self) -> float | None:
        rr = self.rr_ms
        if len(self.r_peaks) < MIN_R_PEAKS:
            return None
        return float(np.sqrt(np.mean(np.diff(rr) ** 2)))


def ecg_strip(samples: Iterable[float], fs: float) -> EcgStrip:
    import neurokit2 as nk

    x = np.asarray(list(samples), dtype=float)
    cleaned = np.asarray(nk.signal_filter(x, sampling_rate=fs, lowcut=ECG_BAND_HZ[0],
                                          highcut=ECG_BAND_HZ[1], method="butterworth",
                                          order=ECG_FILTER_ORDER), dtype=float)
    _, info = nk.ecg_peaks(cleaned, sampling_rate=fs, method="neurokit")
    return EcgStrip(cleaned, np.asarray(info["ECG_R_Peaks"], dtype=int), fs)


@lru_cache(maxsize=1)
def _dropout_bounds() -> dict[str, tuple[float, float]]:
    bounds = plausibility_bounds()
    return {code: (float(bounds[name]["min"]), float(bounds[name]["max"]))
            for code, name in DROPOUT_FIELDS.items()}


def is_dropout(p: Mapping[str, Any]) -> bool:
    limits = _dropout_bounds().get(str(p["code"]["code"]))
    if limits is None or p["code"]["system"] != LOINC:
        return False
    v = p["value"]
    return not (isinstance(v, int | float) and math.isfinite(v) and limits[0] <= v <= limits[1])


def _scalar(v: Any) -> bool:
    return isinstance(v, int | float) and not isinstance(v, bool) and math.isfinite(v)


def _derived(p: Mapping[str, Any], system: str, code: str, value: float,
             unit: str) -> dict[str, Any]:
    return {**p, "code": {"system": system, "code": code, "display": None}, "alt_codes": [],
            "value": value, "unit": unit, "source": "derived"}


def _ecg(p: dict[str, Any]) -> list[dict[str, Any]]:
    wave = p["value"]
    fs = 1000.0 / float(wave["period_ms"])
    strip = ecg_strip(wave["array"], fs)
    out = [{**p, "value": {"array": [float(v) for v in strip.cleaned],
                           "period_ms": wave["period_ms"]}}]
    if (hr := strip.heart_rate) is not None:
        out.append(_derived(p, LOINC, HEART_RATE, hr, "/min"))
    if (rmssd := strip.rmssd) is not None:
        out.append(_derived(p, FIELD_SYSTEM, "hrv_rmssd", rmssd, "ms"))
    return out


def _window_start(t: datetime, window_s: float) -> datetime:
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    seconds = (t.astimezone(UTC) - epoch).total_seconds()
    return epoch + timedelta(seconds=math.floor(seconds / window_s) * window_s)


type _Key = tuple[str, str, str, str, datetime]


def _window(key: _Key, members: list[Mapping[str, Any]], window_s: float) -> FeatureWindow:
    hdt_id, system, code, unit, start = key
    values = [float(m["value"]) for m in members]
    return FeatureWindow(hdt_id, {"system": system, "code": code, "display": None}, unit,
                         start, window_s, float(np.mean(values)), min(values), max(values),
                         tuple(members))


class WindowAccumulator:
    """Scalar readings collected into windows; a window is closed once the clock passes its
    end, so a window that spans two batches is still summarised once."""

    def __init__(self, window_s: float) -> None:
        self.window_s = window_s
        self._open: dict[_Key, list[Mapping[str, Any]]] = defaultdict(list)

    def add(self, payloads: Iterable[Mapping[str, Any]]) -> None:
        for p in payloads:
            if not _scalar(p["value"]):
                continue
            start = _window_start(datetime.fromisoformat(str(p["effective_time"])),
                                  self.window_s)
            self._open[(str(p["hdt_id"]), str(p["code"]["system"]), str(p["code"]["code"]),
                        str(p["unit"]), start)].append(p)

    def __len__(self) -> int:
        return sum(len(v) for v in self._open.values())

    def close(self, now: datetime | None = None) -> list[FeatureWindow]:
        """The windows that end at or before `now`; every window when `now` is None."""
        done = [k for k in self._open
                if now is None or k[4] + timedelta(seconds=self.window_s) <= now]
        done.sort(key=lambda k: (k[0], k[4], k[2]))
        return [_window(k, self._open.pop(k), self.window_s) for k in done]


class Preprocessor:
    def __init__(self, *, window_s: float = 60.0) -> None:
        self.windows = WindowAccumulator(window_s)

    def process(self, payloads: Iterable[dict[str, Any]],
                now: datetime | None = None) -> Preprocessed:
        """Clean one batch; `features` holds the windows closed at `now`."""
        result = Preprocessed()
        for p in payloads:
            if p["code"]["code"] == ECG_CODE and isinstance(p["value"], Mapping):
                result.payloads += _ecg(p)
            elif is_dropout(p):
                result.dropouts += 1
            else:
                result.payloads.append(p)
        self.windows.add(result.payloads)
        result.features = self.windows.close(now)
        return result
