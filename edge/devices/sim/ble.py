"""BLE GATT device simulators: each notification is the characteristic value its device
sends (codecs in `edge.devices.decode.gatt`)."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from edge.devices.decode.gatt import (
    DateTime,
    blood_pressure,
    glucose,
    heart_rate,
    plx,
    temperature,
    weight,
)
from edge.devices.sim.base import Simulator
from edge.devices.transport import BleLink

RR_UNIT_S = 1 / 1024


@dataclass
class Smartwatch(Simulator):
    """Heart Rate Measurement with RR intervals. Successive RR intervals differ by a normal
    step whose SD is the truth's `hrv_rmssd`, so their RMS successive difference estimates it.
    Eight intervals fill the 18 bytes left in a default 23-byte ATT MTU notification."""

    beats_per_frame: int = 8

    def run(self, link: BleLink) -> None:
        for t in self.schedule("heart_rate"):
            hr = self.measure("heart_rate", t)
            rr_s = 60.0 / hr
            rmssd = self.stream.at("hrv_rmssd", t) / 1000 if self.stream.has("hrv_rmssd") else 0
            steps = self.rng.normal(0.0, rmssd, self.beats_per_frame)
            rr = rr_s + np.cumsum(steps) - steps.mean()
            m = heart_rate.HeartRateMeasurement(
                round(hr), sensor_contact_supported=True, sensor_contact_detected=True,
                rr_intervals=tuple(round(v / RR_UNIT_S) for v in rr))
            link.notify(self.device_id, heart_rate.UUID, heart_rate.encode(m),
                        self.stream.when(t))


@dataclass
class BpCuff(Simulator):
    def run(self, link: BleLink) -> None:
        for t in self.schedule("sbp"):
            sbp, dbp = self.measure("sbp", t), self.measure("dbp", t)
            m = blood_pressure.BloodPressureMeasurement(
                round(sbp), round(dbp), round(dbp + (sbp - dbp) / 3),
                time_stamp=DateTime.of(self.stream.when(t)),
                pulse_rate=round(self.measure("heart_rate", t)))
            link.notify(self.device_id, blood_pressure.UUID, blood_pressure.encode(m),
                        self.stream.when(t))


@dataclass
class Glucometer(Simulator):
    """Capillary whole blood from the finger, sent in mol/L (the field unit is mmol/L)."""

    def run(self, link: BleLink) -> None:
        for seq, t in enumerate(self.schedule("glucose")):
            m = glucose.GlucoseMeasurement(
                seq, DateTime.of(self.stream.when(t)),
                concentration=round(self.measure("glucose", t), 1) / 1000, mol_per_l=True)
            link.notify(self.device_id, glucose.UUID, glucose.encode(m),
                        self.stream.when(t))


@dataclass
class PulseOximeter(Simulator):
    def run(self, link: BleLink) -> None:
        for t in self.schedule("spo2"):
            m = plx.PlxContinuousMeasurement(
                plx.SpO2PR(round(self.measure("spo2", t)), round(self.measure("heart_rate", t))))
            link.notify(self.device_id, plx.UUID, plx.encode(m),
                        self.stream.when(t))


@dataclass
class Scale(Simulator):
    """Weight with BMI and height (height from the truth in cm, sent in m)."""

    def run(self, link: BleLink) -> None:
        for t in self.schedule("weight"):
            w = self.measure("weight", t)
            h = self.stream.at("height", t) / 100
            m = weight.WeightMeasurement(round(w / 0.005) * 0.005,
                                         time_stamp=DateTime.of(self.stream.when(t)),
                                         bmi=round(w / h ** 2, 1), height=round(h, 3))
            link.notify(self.device_id, weight.UUID, weight.encode(m),
                        self.stream.when(t))


@dataclass
class Thermometer(Simulator):
    def run(self, link: BleLink) -> None:
        for t in self.schedule("temperature"):
            m = temperature.TemperatureMeasurement(
                round(self.measure("temperature", t), 1),
                time_stamp=DateTime.of(self.stream.when(t)),
                temperature_type=temperature.TYMPANUM)
            link.notify(self.device_id, temperature.UUID, temperature.encode(m),
                        self.stream.when(t))

