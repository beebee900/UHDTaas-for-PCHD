import pytest
from hypothesis import given
from hypothesis import strategies as st

from atra.codes import SYSTEMS, code, system_name
from atra.units import UnitError, compatible, convert, to_pint


@pytest.mark.parametrize(("ucum", "expected"), [
    ("Cel", "degC"), ("mm[Hg]", "mmHg"), ("/min", "1/minute"), ("%", "percent"),
    ("mL/min/{1.73_m2}", "mL/minute"), ("ug/m3", "ug/m**3"), ("10*9/L", "(1e9)/L"),
])
def test_ucum_translation(ucum, expected):
    assert to_pint(ucum) == expected


@pytest.mark.parametrize(("value", "src", "dst", "substance", "expected"), [
    (100, "mg/dL", "mmol/L", "glucose", 5.5507),
    (1.0, "mg/dL", "umol/L", "creatinine", 88.40),
    (37, "Cel", "[degF]", None, 98.6),
    (15, "kPa", "mm[Hg]", None, 112.509),
    (250, "10*3/uL", "10*9/L", None, 250.0),
    (60, "/min", "/h", None, 3600.0),
    (12, "g/dL", "g/L", None, 120.0),
])
def test_convert(value, src, dst, substance, expected):
    assert convert(value, src, dst, substance=substance) == pytest.approx(expected, rel=1e-3)


def test_incompatible_units_raise():
    with pytest.raises(UnitError):
        convert(1, "mmol/L", "mg/dL")
    assert not compatible("kg", "L")


@given(st.floats(min_value=0.5, max_value=40, allow_nan=False))
def test_glucose_round_trip(mmol):
    there = convert(mmol, "mmol/L", "mg/dL", substance="glucose")
    assert convert(there, "mg/dL", "mmol/L", substance="glucose") == pytest.approx(mmol)


def test_code_systems():
    c = code("loinc", "8867-4", "Heart rate")
    assert c.system == SYSTEMS["loinc"]
    assert system_name(c.system) == "loinc"
