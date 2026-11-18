"""Blood Pressure Measurement characteristic (UUID 0x2A35).

Source: Bluetooth GATT Specification Supplement (2026-09-09), section 3.34, Tables 3.52 to
3.55. Pressures are SFLOAT in mmHg, or in kPa when flag bit 0 is set.
"""

from __future__ import annotations

from dataclasses import dataclass

from edge.devices.decode.gatt._wire import DateTime, Reader, Writer, flag

UUID = 0x2A35
UNKNOWN_USER = 0xFF

# Measurement Status bits (Table 3.55).
BODY_MOVEMENT = 1 << 0
CUFF_TOO_LOOSE = 1 << 1
IRREGULAR_PULSE = 1 << 2
PULSE_RATE_ABOVE_RANGE = 0b01 << 3
PULSE_RATE_BELOW_RANGE = 0b10 << 3
IMPROPER_POSITION = 1 << 5


@dataclass(frozen=True)
class BloodPressureMeasurement:
    systolic: float
    diastolic: float
    mean_arterial: float
    kpa: bool = False
    time_stamp: DateTime | None = None
    pulse_rate: float | None = None
    user_id: int | None = None
    status: int | None = None


def encode(m: BloodPressureMeasurement) -> bytes:
    flags = (m.kpa | (m.time_stamp is not None) << 1 | (m.pulse_rate is not None) << 2
             | (m.user_id is not None) << 3 | (m.status is not None) << 4)
    w = Writer()
    w.uint(flags, 1)
    for value in (m.systolic, m.diastolic, m.mean_arterial):
        w.sfloat(value)
    if m.time_stamp is not None:
        m.time_stamp.write(w)
    if m.pulse_rate is not None:
        w.sfloat(m.pulse_rate)
    if m.user_id is not None:
        w.uint(m.user_id, 1)
    if m.status is not None:
        w.uint(m.status, 2)
    return w.bytes()


def decode(data: bytes) -> BloodPressureMeasurement:
    r = Reader(data)
    flags = r.uint(1)
    systolic, diastolic, mean = r.sfloat(), r.sfloat(), r.sfloat()
    stamp = DateTime.read(r) if flag(flags, 1) else None
    pulse = r.sfloat() if flag(flags, 2) else None
    user = r.uint(1) if flag(flags, 3) else None
    status = r.uint(2) if flag(flags, 4) else None
    r.done()
    return BloodPressureMeasurement(systolic, diastolic, mean, flag(flags, 0), stamp, pulse,
                                    user, status)
