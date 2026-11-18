"""Heart Rate Measurement characteristic (UUID 0x2A37).

Source: Bluetooth GATT Specification Supplement (2026-09-09), section 3.126, Tables 3.215 to
3.217. RR-intervals are uint16 in units of 1/1024 s, oldest first.
"""

from __future__ import annotations

from dataclasses import dataclass

from edge.devices.decode.gatt._wire import DecodeError, Reader, Writer, flag

UUID = 0x2A37
RR_UNIT_S = 1 / 1024


@dataclass(frozen=True)
class HeartRateMeasurement:
    heart_rate: int
    """Beats per minute."""
    uint16: bool = False
    sensor_contact_detected: bool = False
    sensor_contact_supported: bool = False
    energy_expended_j: int | None = None
    rr_intervals: tuple[int, ...] | None = None
    """Raw RR-intervals (1/1024 s); None when the RR-Interval flag is clear."""

    @property
    def rr_seconds(self) -> tuple[float, ...]:
        return tuple(v * RR_UNIT_S for v in self.rr_intervals or ())


def encode(m: HeartRateMeasurement) -> bytes:
    if not m.uint16 and m.heart_rate > 0xFF:
        raise ValueError("heart rate above 255 needs the uint16 format")
    flags = (m.uint16 | m.sensor_contact_detected << 1 | m.sensor_contact_supported << 2
             | (m.energy_expended_j is not None) << 3 | (m.rr_intervals is not None) << 4)
    w = Writer()
    w.uint(flags, 1)
    w.uint(m.heart_rate, 2 if m.uint16 else 1)
    if m.energy_expended_j is not None:
        w.uint(m.energy_expended_j, 2)
    for rr in m.rr_intervals or ():
        w.uint(rr, 2)
    return w.bytes()


def decode(data: bytes) -> HeartRateMeasurement:
    r = Reader(data)
    flags = r.uint(1)
    uint16 = flag(flags, 0)
    heart_rate = r.uint(2 if uint16 else 1)
    energy = r.uint(2) if flag(flags, 3) else None
    rr: tuple[int, ...] | None = None
    if flag(flags, 4):
        if r.remaining() % 2:
            raise DecodeError("RR-Interval field has an odd length")
        rr = tuple(r.uint(2) for _ in range(r.remaining() // 2))
    r.done()
    return HeartRateMeasurement(heart_rate, uint16, flag(flags, 1), flag(flags, 2), energy, rr)
