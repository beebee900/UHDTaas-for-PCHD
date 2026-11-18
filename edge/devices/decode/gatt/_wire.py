"""Byte packing shared by the GATT characteristics.

Fields are little-endian and laid out from the least significant octet, in table order
(GATT Specification Supplement 2026-09-09, section 2.4). The Date Time struct is section 3.80.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from edge.devices.decode import medfloat


class DecodeError(ValueError):
    """A characteristic value is too short, too long or malformed."""


class Reader:
    def __init__(self, data: bytes) -> None:
        self.data = bytes(data)
        self.pos = 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise DecodeError(f"value ends at octet {len(self.data)}, needs {self.pos + n}")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def uint(self, n: int) -> int:
        return int.from_bytes(self.take(n), "little")

    def sint(self, n: int) -> int:
        return int.from_bytes(self.take(n), "little", signed=True)

    def sfloat(self) -> float:
        return medfloat.decode_sfloat(self.uint(2))

    def float32(self) -> float:
        return medfloat.decode_float(self.uint(4))

    def remaining(self) -> int:
        return len(self.data) - self.pos

    def done(self) -> None:
        if self.remaining():
            raise DecodeError(f"{self.remaining()} octets left over")


class Writer:
    def __init__(self) -> None:
        self.out = bytearray()

    def uint(self, value: int, n: int) -> None:
        self.out += value.to_bytes(n, "little")

    def sint(self, value: int, n: int) -> None:
        self.out += value.to_bytes(n, "little", signed=True)

    def sfloat(self, value: float | medfloat.Special) -> None:
        self.uint(medfloat.encode_sfloat(value), 2)

    def float32(self, value: float | medfloat.Special) -> None:
        self.uint(medfloat.encode_float(value), 4)

    def bytes(self) -> bytes:
        return bytes(self.out)


def flag(flags: int, bit: int) -> bool:
    return bool(flags >> bit & 1)


@dataclass(frozen=True)
class DateTime:
    """Date Time (section 3.80). A zero year, month or day means "not known"."""

    year: int
    month: int
    day: int
    hours: int
    minutes: int
    seconds: int

    @classmethod
    def of(cls, t: datetime) -> DateTime:
        return cls(t.year, t.month, t.day, t.hour, t.minute, t.second)

    def to_datetime(self) -> datetime | None:
        """The calendar time, or None when a date part is not known."""
        if not (self.year and self.month and self.day):
            return None
        return datetime(self.year, self.month, self.day, self.hours, self.minutes, self.seconds)

    def write(self, w: Writer) -> None:
        w.uint(self.year, 2)
        for part in (self.month, self.day, self.hours, self.minutes, self.seconds):
            w.uint(part, 1)

    @classmethod
    def read(cls, r: Reader) -> DateTime:
        return cls(r.uint(2), r.uint(1), r.uint(1), r.uint(1), r.uint(1), r.uint(1))
