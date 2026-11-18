import math

import pytest
from hypothesis import given
from hypothesis import strategies as st

from edge.devices.decode import medfloat
from edge.devices.decode.medfloat import FLOAT, SFLOAT, Special

FORMATS = {"sfloat": SFLOAT, "float": FLOAT}


@pytest.mark.parametrize(("fmt", "special", "raw"), [
    (SFLOAT, Special.NAN, 0x07FF), (SFLOAT, Special.POSITIVE_INFINITY, 0x07FE),
    (SFLOAT, Special.NEGATIVE_INFINITY, 0x0802), (SFLOAT, Special.NRES, 0x0800),
    (SFLOAT, Special.RESERVED, 0x0801),
    (FLOAT, Special.NAN, 0x007FFFFF), (FLOAT, Special.POSITIVE_INFINITY, 0x007FFFFE),
    (FLOAT, Special.NEGATIVE_INFINITY, 0x00800002), (FLOAT, Special.NRES, 0x00800000),
    (FLOAT, Special.RESERVED, 0x00800001),
])
def test_special_values_match_gss_table_2_1(fmt, special, raw):
    assert medfloat.encode(special, fmt) == raw
    assert medfloat.split(raw, fmt) is special


def test_special_values_decode_to_ieee_floats():
    assert math.isnan(medfloat.decode_sfloat(0x07FF))
    assert math.isnan(medfloat.decode_sfloat(0x0800))
    assert medfloat.decode_sfloat(0x07FE) == math.inf
    assert medfloat.decode_float(0x00800002) == -math.inf
    assert medfloat.encode_sfloat(math.nan) == 0x07FF
    assert medfloat.encode_float(-math.inf) == 0x00800002


@pytest.mark.parametrize(("raw", "value"), [
    (0x0078, 120.0), (0xF258, 60.0), (0xFF0002FA, 76.2), (0xFF0000F3, 24.3), (0x0000, 0.0),
    (0xFFFF, -0.1), (0x8001, 1e-08),
])
def test_known_words(raw, value):
    fmt = SFLOAT if raw <= 0xFFFF else FLOAT
    assert medfloat.decode(raw, fmt) == pytest.approx(value)


@pytest.mark.parametrize("name", FORMATS)
@given(data=st.data())
def test_every_numeric_word_round_trips_by_value(name, data):
    fmt = FORMATS[name]
    mantissa = data.draw(st.integers(-fmt.mantissa_max, fmt.mantissa_max))
    exponent = data.draw(st.integers(fmt.exponent_min, fmt.exponent_max))
    raw = medfloat.join(mantissa, exponent, fmt)
    assert medfloat.split(raw, fmt) == (mantissa, exponent)
    value = medfloat.decode(raw, fmt)
    assert medfloat.decode(medfloat.encode(value, fmt), fmt) == value


@pytest.mark.parametrize("name", FORMATS)
@given(data=st.data())
def test_encode_is_within_half_a_unit(name, data):
    fmt = FORMATS[name]
    limit = fmt.mantissa_max * 10.0 ** fmt.exponent_max
    value = data.draw(st.floats(-limit, limit, allow_nan=False))
    raw = medfloat.encode(value, fmt)
    assert abs(medfloat.decode(raw, fmt) - value) <= medfloat.resolution(raw, fmt) * (1 + 1e-12)


def test_fixed_exponent_and_overflow():
    assert medfloat.split(medfloat.encode_sfloat(36.66, exponent=-1), SFLOAT) == (367, -1)
    assert medfloat.encode_sfloat(1e12) == SFLOAT.special[Special.NRES]
    with pytest.raises(ValueError, match="mantissa"):
        medfloat.encode_sfloat(5000, exponent=0)
