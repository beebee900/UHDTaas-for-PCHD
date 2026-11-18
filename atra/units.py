"""UCUM unit codes and conversion through `pint` (design 02, section 2.8).

UCUM codes are translated to pint expressions. Annotations in braces, such as
`{1.73_m2}` or `{beats}`, are dimensionless in UCUM and are dropped. Conversions
between mass and amount concentration need the substance's molar mass.
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any

import pint

_SPECIAL: dict[str, str] = {
    "Cel": "degC",
    "[degF]": "degF",
    "mm[Hg]": "mmHg",
    "cm[H2O]": "cmH2O",
    "%": "percent",
    "1": "dimensionless",
    "[in_i]": "inch",
    "[lb_av]": "pound",
    "[ft_i]": "foot",
    "[iU]": "IU",
    "[IU]": "IU",
    "/min": "1/minute",
    "/h": "1/hour",
    "/d": "1/day",
    "dB": "decibel",
}

_BRACKETED: dict[str, str] = {
    "mm[Hg]": "mmHg", "cm[H2O]": "cmH2O", "[IU]": "IU", "[iU]": "IU", "[in_i]": "inch",
    "[lb_av]": "pound", "[ft_i]": "foot", "[degF]": "degF",
}

_ATOMS: dict[str, str] = {
    "min": "minute", "h": "hour", "d": "day", "wk": "week", "mo": "month", "a": "year",
    "s": "second", "ms": "millisecond", "U": "enzyme_unit", "Cel": "degC",
}

# Molar masses in g/mol, for mass <-> amount conversions of common analytes.
MOLAR_MASS: dict[str, float] = {
    "glucose": 180.156,
    "creatinine": 113.12,
    "urea": 60.06,
    "bilirubin": 584.66,
    "cholesterol": 386.65,
    "triglyceride": 885.7,
    "uric_acid": 168.11,
    "lactate": 89.07,
    "calcium": 40.078,
    "magnesium": 24.305,
    "phosphate": 30.974,
}


class UnitError(ValueError):
    """A UCUM code cannot be translated or the units are incompatible."""


@lru_cache(maxsize=1)
def registry() -> pint.UnitRegistry:
    ureg = pint.UnitRegistry(autoconvert_offset_to_baseunit=True)
    ureg.define("IU = [international_unit]")
    ureg.define("cmH2O = 98.0665 * pascal")
    return ureg


@lru_cache(maxsize=512)
def to_pint(ucum: str) -> str:
    """Translate one UCUM code to a pint expression."""
    code = re.sub(r"\{[^}]*\}", "", ucum.strip()).rstrip("/.")
    if not code or code == "/":
        return "dimensionless"
    if code in _SPECIAL:
        return _SPECIAL[code]
    if code.startswith("/"):
        code = "1" + code
    code = re.sub(r"10\*(-?\d+)", r"(1e\1)", code)
    for bracketed, plain in _BRACKETED.items():
        code = code.replace(bracketed, plain)
    if "[" in code:
        raise UnitError(f"cannot translate UCUM '{ucum}'")
    parts = re.split(r"([/.])", code)
    out: list[str] = []
    for part in parts:
        if part == "/":
            out.append("/")
        elif part == ".":
            out.append("*")
        elif part:
            m = re.fullmatch(r"([A-Za-z_]+)(-?\d+)?", part)
            if m:
                atom = _ATOMS.get(m.group(1), m.group(1))
                out.append(f"{atom}**{m.group(2)}" if m.group(2) else atom)
            else:
                out.append(part)
    expr = "".join(out).replace("//", "/")
    try:
        registry().parse_expression(expr)
    except (pint.errors.UndefinedUnitError, pint.errors.DefinitionSyntaxError,
            AttributeError, SyntaxError) as exc:
        raise UnitError(f"cannot translate UCUM '{ucum}'") from exc
    return expr


def quantity(value: float, ucum: str) -> Any:
    expr = to_pint(ucum)
    if expr in ("degC", "degF"):
        return registry().Quantity(value, expr)
    return value * registry().parse_expression(expr)


def convert(value: float, from_ucum: str, to_ucum: str, *, substance: str | None = None) -> float:
    """Convert `value` between UCUM units; `substance` enables mass <-> amount conversion."""
    if from_ucum == to_ucum:
        return value
    ureg = registry()
    q = quantity(value, from_ucum)
    target = quantity(1, to_ucum)
    try:
        return _ratio(q, target)
    except pint.errors.DimensionalityError:
        if substance is None:
            raise UnitError(f"{from_ucum} and {to_ucum} are incompatible") from None
    if substance not in MOLAR_MASS:
        raise UnitError(f"no molar mass for '{substance}'")
    mm = ureg.Quantity(MOLAR_MASS[substance], "g/mol")
    for candidate in (q / mm, q * mm):
        try:
            return _ratio(candidate, target)
        except pint.errors.DimensionalityError:
            continue
    raise UnitError(f"{from_ucum} and {to_ucum} are incompatible for {substance}")


def _ratio(q: Any, target: Any) -> float:
    """Magnitude of q in the units of target, where target may carry a numeric factor."""
    if hasattr(target, "units") and target.magnitude == 1:
        return float(q.to(target.units).magnitude)
    return float((q / target).to("dimensionless").magnitude)


def compatible(a: str, b: str) -> bool:
    return bool(quantity(1, a).dimensionality == quantity(1, b).dimensionality)
