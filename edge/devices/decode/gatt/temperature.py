"""Temperature Measurement characteristic (UUID 0x2A1C).

Source: Bluetooth GATT Specification Supplement (2026-09-09), section 3.239, Tables 3.365 and
3.366; Temperature Type values from section 3.242, Table 3.370. The value is FLOAT
(medfloat32) in °C, or °F when flag bit 0 is set.
"""

from __future__ import annotations

from dataclasses import dataclass

from edge.devices.decode.gatt._wire import DateTime, Reader, Writer, flag

UUID = 0x2A1C

# Temperature Type (Table 3.370).
ARMPIT = 1
BODY = 2
EAR = 3
FINGER = 4
GASTROINTESTINAL = 5
MOUTH = 6
RECTUM = 7
TOE = 8
TYMPANUM = 9


@dataclass(frozen=True)
class TemperatureMeasurement:
    value: float
    fahrenheit: bool = False
    time_stamp: DateTime | None = None
    temperature_type: int | None = None

    @property
    def ucum(self) -> str:
        return "[degF]" if self.fahrenheit else "Cel"


def encode(m: TemperatureMeasurement) -> bytes:
    flags = m.fahrenheit | (m.time_stamp is not None) << 1 | (m.temperature_type is not None) << 2
    w = Writer()
    w.uint(flags, 1)
    w.float32(m.value)
    if m.time_stamp is not None:
        m.time_stamp.write(w)
    if m.temperature_type is not None:
        w.uint(m.temperature_type, 1)
    return w.bytes()


def decode(data: bytes) -> TemperatureMeasurement:
    r = Reader(data)
    flags = r.uint(1)
    value = r.float32()
    stamp = DateTime.read(r) if flag(flags, 1) else None
    kind = r.uint(1) if flag(flags, 2) else None
    r.done()
    return TemperatureMeasurement(value, flag(flags, 0), stamp, kind)
