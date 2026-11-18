"""Glucose Measurement characteristic (UUID 0x2A18).

Source: Bluetooth GATT Specification Supplement (2026-09-09), section 3.119, Tables 3.191 to
3.197. The concentration is SFLOAT in kg/L (flag bit 2 clear) or mol/L (flag bit 2 set). The
Type-Sample Location octet holds the type in its low nibble and the location in its high nibble
(section 2.4 ordering).
"""

from __future__ import annotations

from dataclasses import dataclass

from edge.devices.decode.gatt._wire import DateTime, Reader, Writer, flag

UUID = 0x2A18

# Type field (Table 3.195).
CAPILLARY_WHOLE_BLOOD = 0x1
CAPILLARY_PLASMA = 0x2
VENOUS_WHOLE_BLOOD = 0x3
VENOUS_PLASMA = 0x4
ARTERIAL_WHOLE_BLOOD = 0x5
ARTERIAL_PLASMA = 0x6
UNDETERMINED_WHOLE_BLOOD = 0x7
UNDETERMINED_PLASMA = 0x8
INTERSTITIAL_FLUID = 0x9
CONTROL_SOLUTION = 0xA

# Sample Location field (Table 3.196).
FINGER = 0x1
ALTERNATE_SITE = 0x2
EARLOBE = 0x3
LOCATION_CONTROL_SOLUTION = 0x4
LOCATION_NOT_AVAILABLE = 0xF


@dataclass(frozen=True)
class GlucoseMeasurement:
    sequence_number: int
    base_time: DateTime
    time_offset_min: int | None = None
    concentration: float | None = None
    """kg/L, or mol/L when `mol_per_l` is set. None when flag bit 1 is clear."""
    sample_type: int = CAPILLARY_WHOLE_BLOOD
    sample_location: int = FINGER
    mol_per_l: bool = False
    sensor_status: int | None = None
    context_follows: bool = False

    @property
    def ucum(self) -> str:
        return "mol/L" if self.mol_per_l else "kg/L"


def encode(m: GlucoseMeasurement) -> bytes:
    flags = ((m.time_offset_min is not None) | (m.concentration is not None) << 1
             | m.mol_per_l << 2 | (m.sensor_status is not None) << 3 | m.context_follows << 4)
    w = Writer()
    w.uint(flags, 1)
    w.uint(m.sequence_number, 2)
    m.base_time.write(w)
    if m.time_offset_min is not None:
        w.sint(m.time_offset_min, 2)
    if m.concentration is not None:
        w.sfloat(m.concentration)
        w.uint((m.sample_location & 0xF) << 4 | (m.sample_type & 0xF), 1)
    if m.sensor_status is not None:
        w.uint(m.sensor_status, 2)
    return w.bytes()


def decode(data: bytes) -> GlucoseMeasurement:
    r = Reader(data)
    flags = r.uint(1)
    sequence = r.uint(2)
    base = DateTime.read(r)
    offset = r.sint(2) if flag(flags, 0) else None
    concentration: float | None = None
    sample_type, location = CAPILLARY_WHOLE_BLOOD, FINGER
    if flag(flags, 1):
        concentration = r.sfloat()
        octet = r.uint(1)
        sample_type, location = octet & 0xF, octet >> 4
    status = r.uint(2) if flag(flags, 3) else None
    r.done()
    return GlucoseMeasurement(sequence, base, offset, concentration, sample_type, location,
                              flag(flags, 2), status, flag(flags, 4))
