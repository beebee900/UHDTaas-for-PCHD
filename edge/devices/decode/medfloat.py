"""IEEE 11073-20601 SFLOAT (medfloat16) and FLOAT (medfloat32) numbers.

A value is `mantissa × 10^exponent`, both two's-complement integers packed into one word:

- SFLOAT: 4-bit exponent (high bits), 12-bit mantissa
- FLOAT: 8-bit exponent (high byte), 24-bit mantissa

Sources:
- Bluetooth GATT Specification Supplement (2026-09-09), section 2.1 (medfloat16 = SFLOAT,
  medfloat32 = FLOAT) and Table 2.1 (special values).
- Bluetooth Pulse Oximeter Service v1.0.1, section 5.1 (meaning of NaN and NRes).
- The bit layout and the reserved mantissa range follow the Antidote stack
  (`src/util/bytelib.c`, `read_sfloat`/`read_float`, citing MDER Annex F.6 and F.7).

Special values are recognised by their mantissa, as Antidote does, and written with exponent 0
as in Table 2.1. NRes and the reserved value decode to NaN.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from enum import Enum


class Special(Enum):
    NAN = "nan"
    NRES = "nres"
    POSITIVE_INFINITY = "+inf"
    NEGATIVE_INFINITY = "-inf"
    RESERVED = "reserved"


@dataclass(frozen=True)
class _Format:
    exponent_bits: int
    mantissa_bits: int
    special: dict[Special, int]

    @property
    def mantissa_max(self) -> int:
        """Largest numeric mantissa; the five values above it (in two's complement) are special."""
        return (1 << (self.mantissa_bits - 1)) - 3

    @property
    def exponent_min(self) -> int:
        return -(1 << (self.exponent_bits - 1))

    @property
    def exponent_max(self) -> int:
        return (1 << (self.exponent_bits - 1)) - 1


SFLOAT = _Format(4, 12, {
    Special.NAN: 0x07FF,
    Special.NRES: 0x0800,
    Special.POSITIVE_INFINITY: 0x07FE,
    Special.NEGATIVE_INFINITY: 0x0802,
    Special.RESERVED: 0x0801,
})
FLOAT = _Format(8, 24, {
    Special.NAN: 0x007FFFFF,
    Special.NRES: 0x00800000,
    Special.POSITIVE_INFINITY: 0x007FFFFE,
    Special.NEGATIVE_INFINITY: 0x00800002,
    Special.RESERVED: 0x00800001,
})

_AS_FLOAT = {
    Special.NAN: math.nan,
    Special.NRES: math.nan,
    Special.RESERVED: math.nan,
    Special.POSITIVE_INFINITY: math.inf,
    Special.NEGATIVE_INFINITY: -math.inf,
}


def _signed(value: int, bits: int) -> int:
    return value - (1 << bits) if value & (1 << (bits - 1)) else value


def split(raw: int, fmt: _Format) -> tuple[int, int] | Special:
    """`(mantissa, exponent)` of a raw word, or its special value."""
    mask = (1 << fmt.mantissa_bits) - 1
    for special, word in fmt.special.items():
        if raw & mask == word:
            return special
    return (_signed(raw & mask, fmt.mantissa_bits),
            _signed(raw >> fmt.mantissa_bits, fmt.exponent_bits))


def join(mantissa: int, exponent: int, fmt: _Format) -> int:
    """The raw word for a numeric mantissa and exponent."""
    if abs(mantissa) > fmt.mantissa_max:
        raise ValueError(f"mantissa {mantissa} is outside ±{fmt.mantissa_max}")
    if not fmt.exponent_min <= exponent <= fmt.exponent_max:
        raise ValueError(f"exponent {exponent} is outside {fmt.exponent_min}..{fmt.exponent_max}")
    mask = (1 << fmt.mantissa_bits) - 1
    return ((exponent & ((1 << fmt.exponent_bits) - 1)) << fmt.mantissa_bits) | (mantissa & mask)


def decode(raw: int, fmt: _Format) -> float:
    parts = split(raw, fmt)
    if isinstance(parts, Special):
        return _AS_FLOAT[parts]
    mantissa, exponent = parts
    return float(Decimal(mantissa).scaleb(exponent))


def parts_of(value: float, fmt: _Format, exponent: int | None = None) -> tuple[int, int] | Special:
    """Mantissa and exponent for `value`.

    With `exponent` given, the value is rounded to that resolution. Without it, the finest
    resolution whose mantissa fits is used. A value that fits no exponent is NRes.
    """
    if math.isnan(value):
        return Special.NAN
    if math.isinf(value):
        return Special.POSITIVE_INFINITY if value > 0 else Special.NEGATIVE_INFINITY
    exact = Decimal(repr(value))
    if exponent is not None:
        mantissa = int(exact.scaleb(-exponent).to_integral_value(ROUND_HALF_EVEN))
        join(mantissa, exponent, fmt)
        return mantissa, exponent
    if value == 0:
        return 0, 0
    for exp in range(fmt.exponent_min, fmt.exponent_max + 1):
        mantissa = int(exact.scaleb(-exp).to_integral_value(ROUND_HALF_EVEN))
        if abs(mantissa) <= fmt.mantissa_max:
            return mantissa, exp
    return Special.NRES


def encode(value: float | Special, fmt: _Format, exponent: int | None = None) -> int:
    parts = value if isinstance(value, Special) else parts_of(value, fmt, exponent)
    if isinstance(parts, Special):
        return fmt.special[parts]
    return join(*parts, fmt)


def encode_sfloat(value: float | Special, exponent: int | None = None) -> int:
    return encode(value, SFLOAT, exponent)


def decode_sfloat(raw: int) -> float:
    return decode(raw, SFLOAT)


def encode_float(value: float | Special, exponent: int | None = None) -> int:
    return encode(value, FLOAT, exponent)


def decode_float(raw: int) -> float:
    return decode(raw, FLOAT)


def resolution(raw: int, fmt: _Format) -> float:
    """Half a unit in the last place of a raw word: the largest rounding error it carries."""
    parts = split(raw, fmt)
    return 0.0 if isinstance(parts, Special) else 0.5 * 10.0 ** parts[1]
