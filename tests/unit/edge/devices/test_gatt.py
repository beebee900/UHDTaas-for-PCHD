"""Encode → decode is the identity, within resolution, for every flag combination."""

import itertools
import math

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from edge.devices.decode import gatt, medfloat
from edge.devices.decode.gatt import (
    DateTime,
    DecodeError,
    blood_pressure,
    glucose,
    heart_rate,
    plx,
    temperature,
    weight,
)

COMBOS = {n: list(itertools.product([False, True], repeat=n)) for n in (3, 4, 5)}

sfloat_values = st.builds(
    lambda m, e: medfloat.decode_sfloat(medfloat.join(m, e, medfloat.SFLOAT)),
    st.integers(-medfloat.SFLOAT.mantissa_max, medfloat.SFLOAT.mantissa_max),
    st.integers(-3, 2))
float_values = st.builds(
    lambda m, e: medfloat.decode_float(medfloat.join(m, e, medfloat.FLOAT)),
    st.integers(-medfloat.FLOAT.mantissa_max, medfloat.FLOAT.mantissa_max), st.integers(-4, 2))
date_times = st.builds(DateTime, st.integers(1582, 9999), st.integers(0, 12), st.integers(0, 31),
                       st.integers(0, 23), st.integers(0, 59), st.integers(0, 59))
u8, u16, u24 = st.integers(0, 0xFF), st.integers(0, 0xFFFF), st.integers(0, 0xFFFFFF)


def maybe(present, strategy):
    return strategy if present else st.none()


@pytest.mark.parametrize("bits", COMBOS[5])
@settings(max_examples=25)
@given(data=st.data())
def test_heart_rate_round_trip(bits, data):
    wide, contact, supported, energy, rr = bits
    m = heart_rate.HeartRateMeasurement(
        data.draw(u16 if wide else u8), wide, contact, supported,
        data.draw(maybe(energy, u16)),
        data.draw(maybe(rr, st.lists(u16, max_size=8).map(tuple))))
    raw = heart_rate.encode(m)
    assert raw[0] == sum(b << i for i, b in enumerate(bits))
    assert gatt.decode(heart_rate.UUID, raw) == m


@pytest.mark.parametrize("bits", COMBOS[5])
@settings(max_examples=25)
@given(data=st.data())
def test_blood_pressure_round_trip(bits, data):
    kpa, stamp, pulse, user, status = bits
    m = blood_pressure.BloodPressureMeasurement(
        data.draw(sfloat_values), data.draw(sfloat_values), data.draw(sfloat_values), kpa,
        data.draw(maybe(stamp, date_times)), data.draw(maybe(pulse, sfloat_values)),
        data.draw(maybe(user, u8)), data.draw(maybe(status, u16)))
    raw = blood_pressure.encode(m)
    assert raw[0] == sum(b << i for i, b in enumerate(bits))
    assert blood_pressure.decode(raw) == m


@pytest.mark.parametrize("bits", COMBOS[5])
@settings(max_examples=25)
@given(data=st.data())
def test_glucose_round_trip(bits, data):
    offset, conc, mol, status, context = bits
    m = glucose.GlucoseMeasurement(
        data.draw(u16), data.draw(date_times), data.draw(maybe(offset, st.integers(-32768, 32767))),
        data.draw(maybe(conc, sfloat_values)),
        data.draw(st.integers(0, 15)) if conc else glucose.CAPILLARY_WHOLE_BLOOD,
        data.draw(st.integers(0, 15)) if conc else glucose.FINGER,
        mol, data.draw(maybe(status, u16)), context)
    raw = glucose.encode(m)
    assert raw[0] == sum(b << i for i, b in enumerate(bits))
    assert glucose.decode(raw) == m


@pytest.mark.parametrize("bits", COMBOS[5])
@settings(max_examples=25)
@given(data=st.data())
def test_plx_round_trip(bits, data):
    fast, slow, status, device, pai = bits
    pair = st.builds(plx.SpO2PR, sfloat_values, sfloat_values)
    m = plx.PlxContinuousMeasurement(
        data.draw(pair), data.draw(maybe(fast, pair)), data.draw(maybe(slow, pair)),
        data.draw(maybe(status, u16)), data.draw(maybe(device, u24)),
        data.draw(maybe(pai, sfloat_values)))
    raw = plx.encode(m)
    assert raw[0] == sum(b << i for i, b in enumerate(bits))
    assert plx.decode(raw) == m


@pytest.mark.parametrize("bits", COMBOS[4])
@settings(max_examples=25)
@given(data=st.data())
def test_weight_round_trip_within_resolution(bits, data):
    imperial, stamp, user, bmi = bits
    step_w, step_h = weight.WEIGHT_STEP[imperial], weight.HEIGHT_STEP[imperial]
    m = weight.WeightMeasurement(
        data.draw(st.floats(0, 0xFFFF * step_w)), imperial,
        data.draw(maybe(stamp, date_times)), data.draw(maybe(user, u8)),
        data.draw(maybe(bmi, st.floats(0, 0xFFFF * weight.BMI_STEP))),
        data.draw(maybe(bmi, st.floats(0, 0xFFFF * step_h))))
    raw = weight.encode(m)
    assert raw[0] == sum(b << i for i, b in enumerate(bits))
    back = weight.decode(raw)
    assert (back.imperial, back.time_stamp, back.user_id) == (imperial, m.time_stamp, m.user_id)
    assert abs(back.weight - m.weight) <= step_w / 2 + 1e-9
    if bmi:
        assert abs(back.bmi - m.bmi) <= weight.BMI_STEP / 2 + 1e-9
        assert abs(back.height - m.height) <= step_h / 2 + 1e-9
    assert weight.decode(weight.encode(back)) == back


@pytest.mark.parametrize("bits", COMBOS[3])
@settings(max_examples=25)
@given(data=st.data())
def test_temperature_round_trip(bits, data):
    fahrenheit, stamp, kind = bits
    m = temperature.TemperatureMeasurement(
        data.draw(float_values), fahrenheit, data.draw(maybe(stamp, date_times)),
        data.draw(maybe(kind, u8)))
    raw = temperature.encode(m)
    assert raw[0] == sum(b << i for i, b in enumerate(bits))
    assert temperature.decode(raw) == m


def test_known_heart_rate_value():
    m = gatt.decode(0x2A37, bytes([0x16, 72, 0x00, 0x04, 0x00, 0x02]))
    assert (m.heart_rate, m.sensor_contact_detected, m.sensor_contact_supported) == (72, 1, 1)
    assert m.rr_seconds == (1.0, 0.5)


def test_special_values_pass_through_fields():
    m = plx.PlxContinuousMeasurement(plx.SpO2PR(math.nan, 61.0))
    back = plx.decode(plx.encode(m))
    assert math.isnan(back.normal.spo2) and back.normal.pulse_rate == 61.0


def test_glucose_type_and_location_nibbles():
    m = glucose.GlucoseMeasurement(1, DateTime(2026, 10, 10, 8, 0, 0), concentration=0.00095,
                                   sample_type=glucose.VENOUS_PLASMA,
                                   sample_location=glucose.LOCATION_NOT_AVAILABLE)
    assert glucose.encode(m)[12] == 0xF4


def test_malformed_values_raise():
    with pytest.raises(DecodeError):
        blood_pressure.decode(bytes([0x02, 0, 0, 0, 0, 0, 0]))
    with pytest.raises(DecodeError):
        heart_rate.decode(bytes([0x00, 60, 1]))
    with pytest.raises(DecodeError):
        gatt.decode(0x2A00, b"")
    with pytest.raises(ValueError, match="uint16"):
        heart_rate.encode(heart_rate.HeartRateMeasurement(300))
