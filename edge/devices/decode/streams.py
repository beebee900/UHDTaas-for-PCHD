"""JSON payloads of the MQTT device classes (design 04, 4.1.1) and their edge pre-processing.

These device protocols are defined by this project, as 4.1.1 states for the insulin pump; the
ESP32 firmware (4.1.3) publishes the same shapes. Times are ISO 8601 with an offset.

| Class | Payload | Readings |
|---|---|---|
| `ecg_patch` | `{t0, fs, gain, baseline, units, adc: [int]}` | `ecg_lead_ii` waveform (mV) |
| `imu` | `{t0, fs, acc: [[x, y, z]], gyro: [[x, y, z]]}`, m/s2 and deg/s | `cadence` |
| `pressure_insoles` | `{t0, fs, left: [[8 x kPa]], right: [[8 x kPa]]}` | `cadence` |
| `insulin_pump` | `{time, kind: basal or bolus, delivered_u}` | `insulin_delivered` |
| `environmental` (DHT22) | `{time, temperature_c, humidity_pct}` | `ambient_temp`, `humidity` |
| `pulse_oximeter` (ESP32 MAX3010x) | `{time, spo2_pct, pulse_rate}` | SpO2 59408-5, HR 8867-4 |
| `phone` | `{t0, fs, acc: [[x, y, z]], gps: [{time, lat, lon}]}` | `active_minutes` |

Cadence counts steps (IMU) or heel strikes (insoles) per minute over the window. A step is a
peak of the acceleration magnitude above gravity by `STEP_THRESHOLD`, at least `STEP_GAP_S`
after the previous one; a heel strike is an upward crossing of half the window's peak total
pressure by the heel sensors of one foot.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from typing import Any

import numpy as np
import numpy.typing as npt

from atra.codes import SYSTEMS
from atra.contracts import Code
from edge.devices.decode.observations import (
    HEART_RATE,
    SPO2,
    CodedReading,
    Reading,
    field_reading,
)

GRAVITY = 9.80665
STEP_THRESHOLD = 1.5
STEP_GAP_S = 0.3
ACTIVE_THRESHOLD = 0.5
HEEL_SENSORS = (0, 1)
ECG_LEAD_II = Code(system=SYSTEMS["mdc"], code="MDC_ECG_ELEC_POTL_II")


class PayloadError(ValueError):
    pass


def _time(value: Any) -> datetime:
    t = datetime.fromisoformat(str(value))
    if t.tzinfo is None:
        raise PayloadError("device times carry a UTC offset")
    return t


def _magnitude(acc: Sequence[Sequence[float]]) -> npt.NDArray[np.float64]:
    a = np.asarray(acc, dtype=float)
    if a.ndim != 2 or a.shape[1] != 3:
        raise PayloadError("acc is a list of [x, y, z] samples")
    out: npt.NDArray[np.float64] = np.linalg.norm(a, axis=1) - GRAVITY
    return out


def count_steps(acc: Sequence[Sequence[float]], fs: float) -> int:
    m = _magnitude(acc)
    gap = int(STEP_GAP_S * fs)
    steps, last = 0, -gap
    for i in range(1, len(m) - 1):
        if m[i] > STEP_THRESHOLD and m[i] >= m[i - 1] and m[i] > m[i + 1] and i - last >= gap:
            steps, last = steps + 1, i
    return steps


def heel_strikes(foot: Sequence[Sequence[float]]) -> int:
    p = np.asarray(foot, dtype=float)
    if p.ndim != 2 or p.shape[1] != 8:
        raise PayloadError("an insole frame has 8 sensors")
    heel = p[:, list(HEEL_SENSORS)].sum(axis=1)
    level = heel.max() / 2
    if level <= 0:
        return 0
    above = heel > level
    return int(np.count_nonzero(above[1:] & ~above[:-1]) + (1 if above[0] else 0))


def ecg(o: Mapping[str, Any]) -> list[CodedReading]:
    fs, gain = float(o["fs"]), float(o["gain"])
    if o.get("units", "mV") != "mV":
        raise PayloadError("the ECG patch reports millivolts")
    mv = [(int(v) - int(o.get("baseline", 0))) / gain for v in o["adc"]]
    return [CodedReading(ECG_LEAD_II, {"array": mv, "period_ms": 1000.0 / fs}, "mV",
                         _time(o["t0"]))]


def imu(o: Mapping[str, Any]) -> list[CodedReading]:
    fs = float(o["fs"])
    minutes = len(o["acc"]) / fs / 60.0
    return field_reading("cadence", count_steps(o["acc"], fs) / minutes, "/min", _time(o["t0"]))


def insoles(o: Mapping[str, Any]) -> list[CodedReading]:
    fs = float(o["fs"])
    if len(o["left"]) != len(o["right"]):
        raise PayloadError("left and right insoles have the same frame count")
    minutes = len(o["left"]) / fs / 60.0
    strikes = heel_strikes(o["left"]) + heel_strikes(o["right"])
    return field_reading("cadence", strikes / minutes, "/min", _time(o["t0"]))


def insulin_pump(o: Mapping[str, Any]) -> list[CodedReading]:
    if o.get("kind") not in ("basal", "bolus"):
        raise PayloadError("an insulin delivery is basal or bolus")
    return field_reading("insulin_delivered", float(o["delivered_u"]), "U", _time(o["time"]))


def dht22(o: Mapping[str, Any]) -> list[CodedReading]:
    t = _time(o["time"])
    return [*field_reading("ambient_temp", float(o["temperature_c"]), "Cel", t),
            *field_reading("humidity", float(o["humidity_pct"]), "%", t)]


def pulse_oximeter(o: Mapping[str, Any]) -> list[Reading]:
    t = _time(o["time"])
    return [Reading(SPO2, float(o["spo2_pct"]), "%", time=t),
            Reading(HEART_RATE, float(o["pulse_rate"]), "/min", time=t)]


def phone(o: Mapping[str, Any]) -> list[CodedReading]:
    fs = float(o["fs"])
    m = np.abs(_magnitude(o["acc"]))
    per_min = round(60 * fs)
    active = sum(1 for i in range(0, len(m), per_min)
                 if m[i:i + per_min].mean() > ACTIVE_THRESHOLD)
    return field_reading("active_minutes", float(active), "min", _time(o["t0"]))


DECODERS: dict[str, Callable[[Mapping[str, Any]], Sequence[Reading | CodedReading]]] = {
    "ecg_patch": ecg, "imu": imu, "pressure_insoles": insoles, "insulin_pump": insulin_pump,
    "environmental": dht22, "pulse_oximeter": pulse_oximeter, "phone": phone}


def decode(device_class: str, payload: bytes) -> list[Reading | CodedReading]:
    try:
        decoder = DECODERS[device_class]
    except KeyError:
        raise PayloadError(f"no MQTT decoder for {device_class}") from None
    try:
        body = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PayloadError(f"payload is not JSON: {exc}") from exc
    return list(decoder(body))
