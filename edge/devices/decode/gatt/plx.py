"""PLX Continuous Measurement characteristic (UUID 0x2A5F).

The GATT Specification Supplement does not define this characteristic. Source: Bluetooth Pulse
Oximeter Service v1.0.1 (2022-01-18), section 3.2, Tables 3.6 and 3.7; status bits in
section 3.1.1.4 (Table 3.4) and 3.1.1.5 (Table 3.5). SpO₂ (%) and pulse rate (/min) are SFLOAT;
an unavailable subfield carries NaN (section 5.1).
"""

from __future__ import annotations

from dataclasses import dataclass

from edge.devices.decode.gatt._wire import Reader, Writer, flag

UUID = 0x2A5F

# Measurement Status bits (Table 3.4).
MEASUREMENT_ONGOING = 1 << 5
EARLY_ESTIMATED_DATA = 1 << 6
VALIDATED_DATA = 1 << 7
FULLY_QUALIFIED_DATA = 1 << 8
FROM_MEASUREMENT_STORAGE = 1 << 9
DEMONSTRATION_DATA = 1 << 10
TESTING_DATA = 1 << 11
CALIBRATION_ONGOING = 1 << 12
MEASUREMENT_UNAVAILABLE = 1 << 13
QUESTIONABLE_MEASUREMENT = 1 << 14
INVALID_MEASUREMENT = 1 << 15

# Device and Sensor Status bits (Table 3.5), 24 bits.
EXTENDED_DISPLAY_UPDATE_ONGOING = 1 << 0
EQUIPMENT_MALFUNCTION = 1 << 1
SIGNAL_PROCESSING_IRREGULARITY = 1 << 2
INADEQUATE_SIGNAL = 1 << 3
POOR_SIGNAL = 1 << 4
LOW_PERFUSION = 1 << 5
ERRATIC_SIGNAL = 1 << 6
NON_PULSATILE_SIGNAL = 1 << 7
QUESTIONABLE_PULSE = 1 << 8
SIGNAL_ANALYSIS_ONGOING = 1 << 9
SENSOR_INTERFERENCE = 1 << 10
SENSOR_UNCONNECTED_TO_USER = 1 << 11
UNKNOWN_SENSOR_CONNECTED = 1 << 12
SENSOR_DISPLACED = 1 << 13
SENSOR_MALFUNCTIONING = 1 << 14
SENSOR_DISCONNECTED = 1 << 15


@dataclass(frozen=True)
class SpO2PR:
    spo2: float
    pulse_rate: float


@dataclass(frozen=True)
class PlxContinuousMeasurement:
    normal: SpO2PR
    fast: SpO2PR | None = None
    slow: SpO2PR | None = None
    measurement_status: int | None = None
    device_sensor_status: int | None = None
    pulse_amplitude_index: float | None = None


def encode(m: PlxContinuousMeasurement) -> bytes:
    flags = ((m.fast is not None) | (m.slow is not None) << 1
             | (m.measurement_status is not None) << 2
             | (m.device_sensor_status is not None) << 3
             | (m.pulse_amplitude_index is not None) << 4)
    w = Writer()
    w.uint(flags, 1)
    for pair in (m.normal, m.fast, m.slow):
        if pair is not None:
            w.sfloat(pair.spo2)
            w.sfloat(pair.pulse_rate)
    if m.measurement_status is not None:
        w.uint(m.measurement_status, 2)
    if m.device_sensor_status is not None:
        w.uint(m.device_sensor_status, 3)
    if m.pulse_amplitude_index is not None:
        w.sfloat(m.pulse_amplitude_index)
    return w.bytes()


def decode(data: bytes) -> PlxContinuousMeasurement:
    r = Reader(data)
    flags = r.uint(1)
    normal = SpO2PR(r.sfloat(), r.sfloat())
    fast = SpO2PR(r.sfloat(), r.sfloat()) if flag(flags, 0) else None
    slow = SpO2PR(r.sfloat(), r.sfloat()) if flag(flags, 1) else None
    status = r.uint(2) if flag(flags, 2) else None
    device = r.uint(3) if flag(flags, 3) else None
    pai = r.sfloat() if flag(flags, 4) else None
    r.done()
    return PlxContinuousMeasurement(normal, fast, slow, status, device, pai)
