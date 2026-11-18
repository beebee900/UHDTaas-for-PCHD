"""MQTT device simulators: JSON payloads of `edge.devices.decode.streams` in MQTT 3.1.1
PUBLISH packets on `dev/{hdt_id}/{device_id}/{class}`.

The raw signals are synthesised from the truth: an ECG beat template repeated at the true
heart rate, acceleration pulses at the true cadence, heel and forefoot loading of the insoles
at the true cadence, and phone movement for the true active minutes. The beat template
(P 0.15 mV, R 1.2 mV, S -0.25 mV, T 0.3 mV Gaussian waves) and the pulse shapes are
illustrative waveforms, not a physiological model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import numpy as np
import numpy.typing as npt

from edge.devices.decode.streams import GRAVITY
from edge.devices.sim.base import Simulator
from edge.devices.transport.mqtt import MqttBroker, Publish, encode_publish

BEAT = ((-0.20, 0.025, 0.15), (-0.03, 0.010, -0.10), (0.0, 0.012, 1.2), (0.03, 0.010, -0.25),
        (0.25, 0.040, 0.30))
"""(offset from the R peak in s, width in s, amplitude in mV)."""
ECG_FS = 250.0
ECG_GAIN = 200.0
STEP_PEAK = 3.0
STEP_WIDTH_S = 0.1
HEEL_KPA = 200.0
FORE_KPA = 150.0
CONTACT_S = 0.25


def _publish(broker: MqttBroker, topic: str, body: Any, packet_id: int) -> None:
    payload = json.dumps(body, separators=(",", ":")).encode()
    broker.publish(encode_publish(Publish(topic, payload, qos=1, packet_id=packet_id)))


def ecg_trace(hr: float, seconds: float, fs: float = ECG_FS) -> npt.NDArray[np.float64]:
    t = np.arange(int(seconds * fs)) / fs
    rr = 60.0 / hr
    phase = (t + rr / 2) % rr - rr / 2
    out = np.zeros_like(t)
    for offset, width, amp in BEAT:
        out += amp * np.exp(-((phase - offset) ** 2) / (2 * width ** 2))
    return out


def _pulses(rate_per_min: float, seconds: float, fs: float, width_s: float,
            offset_s: float = 0.0) -> npt.NDArray[np.float64]:
    t = np.arange(int(seconds * fs)) / fs
    period = 60.0 / rate_per_min
    phase = (t - offset_s) % period
    return np.where(phase < width_s, np.sin(np.pi * phase / width_s), 0.0)


@dataclass
class EcgPatch(Simulator):
    window_s: float = 10.0

    def run(self, broker: MqttBroker) -> None:
        for n, t in enumerate(self.schedule("heart_rate")):
            mv = ecg_trace(self.stream.at("heart_rate", t), self.window_s)
            adc = np.round(mv * ECG_GAIN).astype(int).tolist()
            _publish(broker, self.topic("ecg_patch"), {
                "t0": self.stream.when(t).isoformat(), "fs": ECG_FS, "gain": ECG_GAIN,
                "baseline": 0, "units": "mV", "adc": adc}, n % 65535 + 1)


@dataclass
class Imu(Simulator):
    fs: float = 50.0
    window_s: float = 60.0

    def run(self, broker: MqttBroker) -> None:
        for n, t in enumerate(self.schedule("cadence")):
            z = GRAVITY + STEP_PEAK * _pulses(self.stream.at("cadence", t), self.window_s,
                                              self.fs, STEP_WIDTH_S, 0.05)
            acc = [[0.0, 0.0, round(float(v), 3)] for v in z]
            _publish(broker, self.topic("imu"), {
                "t0": self.stream.when(t).isoformat(), "fs": self.fs, "acc": acc,
                "gyro": [[0.0, 0.0, 0.0]] * len(acc)}, n % 65535 + 1)


@dataclass
class Insoles(Simulator):
    fs: float = 100.0
    window_s: float = 60.0

    def _foot(self, cadence: float, offset_s: float) -> list[list[float]]:
        per_foot = cadence / 2
        heel = HEEL_KPA * _pulses(per_foot, self.window_s, self.fs, CONTACT_S, offset_s)
        fore = FORE_KPA * _pulses(per_foot, self.window_s, self.fs, CONTACT_S,
                                  offset_s + CONTACT_S / 2)
        return [[round(float(h), 1)] * 2 + [round(float(f), 1)] * 6 for h, f in zip(
            heel, fore, strict=True)]

    def run(self, broker: MqttBroker) -> None:
        for n, t in enumerate(self.schedule("cadence")):
            cadence = self.stream.at("cadence", t)
            step = 60.0 / cadence
            _publish(broker, self.topic("pressure_insoles"), {
                "t0": self.stream.when(t).isoformat(), "fs": self.fs,
                "left": self._foot(cadence, 0.05), "right": self._foot(cadence, 0.05 + step)},
                n % 65535 + 1)


@dataclass
class InsulinPump(Simulator):
    """Each truth sample is one delivery; whole units are boluses, the rest basal."""

    def run(self, broker: MqttBroker) -> None:
        for n, t in enumerate(self.schedule("insulin_delivered")):
            dose = round(self.measure("insulin_delivered", t), 2)
            _publish(broker, self.topic("insulin_pump"), {
                "time": self.stream.when(t).isoformat(),
                "kind": "bolus" if dose >= 1 else "basal", "delivered_u": dose}, n % 65535 + 1)


@dataclass
class Dht22(Simulator):
    def run(self, broker: MqttBroker) -> None:
        for n, t in enumerate(self.schedule("ambient_temp")):
            _publish(broker, self.topic("environmental"), {
                "time": self.stream.when(t).isoformat(),
                "temperature_c": round(self.measure("ambient_temp", t), 1),
                "humidity_pct": round(self.measure("humidity", t), 1)}, n % 65535 + 1)


@dataclass
class PhoneSensors(Simulator):
    """One hour of 1 Hz accelerometer per truth sample: the first `active_minutes` minutes
    move at 1 m/s2 above gravity. GPS fixes repeat the `home` location."""

    fs: float = 1.0
    home: tuple[float, float] = (6.4969, 3.3612)

    def run(self, broker: MqttBroker) -> None:
        per_min = round(60 * self.fs)
        for n, t in enumerate(self.schedule("active_minutes")):
            active = round(self.stream.at("active_minutes", t))
            acc = [[0.0, 0.0, GRAVITY + (1.0 if i // per_min < active else 0.0)]
                   for i in range(60 * per_min)]
            when = self.stream.when(t).isoformat()
            _publish(broker, self.topic("phone"), {
                "t0": when, "fs": self.fs, "acc": acc,
                "gps": [{"time": when, "lat": self.home[0], "lon": self.home[1]}]},
                n % 65535 + 1)
