"""Weight Measurement characteristic (UUID 0x2A9D).

Source: Bluetooth GATT Specification Supplement (2026-09-09), section 3.276, Tables 3.408 and
3.409. Weight is uint16 at 0.005 kg (SI) or 0.01 lb (imperial); BMI is uint16 at 0.1 kg/m²;
height is uint16 at 0.001 m (SI) or 0.1 in (imperial). BMI and height travel together.
"""

from __future__ import annotations

from dataclasses import dataclass

from edge.devices.decode.gatt._wire import DateTime, Reader, Writer, flag

UUID = 0x2A9D
UNKNOWN_USER = 0xFF

WEIGHT_STEP = {False: 0.005, True: 0.01}
HEIGHT_STEP = {False: 0.001, True: 0.1}
BMI_STEP = 0.1


@dataclass(frozen=True)
class WeightMeasurement:
    weight: float
    """kg, or lb when `imperial` is set."""
    imperial: bool = False
    time_stamp: DateTime | None = None
    user_id: int | None = None
    bmi: float | None = None
    height: float | None = None
    """m, or in when `imperial` is set. Present exactly when `bmi` is."""

    @property
    def weight_ucum(self) -> str:
        return "[lb_av]" if self.imperial else "kg"

    @property
    def height_ucum(self) -> str:
        return "[in_i]" if self.imperial else "m"


def _steps(value: float, step: float) -> int:
    raw = round(value / step)
    if not 0 <= raw <= 0xFFFF:
        raise ValueError(f"{value} is outside the uint16 range at resolution {step}")
    return raw


def encode(m: WeightMeasurement) -> bytes:
    if (m.bmi is None) != (m.height is None):
        raise ValueError("BMI and height are sent together")
    flags = (m.imperial | (m.time_stamp is not None) << 1 | (m.user_id is not None) << 2
             | (m.bmi is not None) << 3)
    w = Writer()
    w.uint(flags, 1)
    w.uint(_steps(m.weight, WEIGHT_STEP[m.imperial]), 2)
    if m.time_stamp is not None:
        m.time_stamp.write(w)
    if m.user_id is not None:
        w.uint(m.user_id, 1)
    if m.bmi is not None and m.height is not None:
        w.uint(_steps(m.bmi, BMI_STEP), 2)
        w.uint(_steps(m.height, HEIGHT_STEP[m.imperial]), 2)
    return w.bytes()


def decode(data: bytes) -> WeightMeasurement:
    r = Reader(data)
    flags = r.uint(1)
    imperial = flag(flags, 0)
    weight = r.uint(2) * WEIGHT_STEP[imperial]
    stamp = DateTime.read(r) if flag(flags, 1) else None
    user = r.uint(1) if flag(flags, 2) else None
    bmi = height = None
    if flag(flags, 3):
        bmi = r.uint(2) * BMI_STEP
        height = r.uint(2) * HEIGHT_STEP[imperial]
    r.done()
    return WeightMeasurement(weight, imperial, stamp, user, bmi, height)
