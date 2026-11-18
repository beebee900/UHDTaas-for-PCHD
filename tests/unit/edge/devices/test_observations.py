"""Decoded readings reach the ingestion contract with LOINC codes, MDC alt codes and UCUM units."""

import math
from datetime import UTC, datetime

import pytest

from ahdt.ingest.fields import field_index
from ahdt.ingest.harmonise import harmonise
from ahdt.ingest.pipeline import raw_from_payload
from atra.codes import SYSTEMS, table
from edge.devices.decode import gatt, phd
from edge.devices.decode.gatt import (
    DateTime,
    blood_pressure,
    glucose,
    heart_rate,
    plx,
    temperature,
    weight,
)
from edge.devices.decode.observations import LOINC_OF_MDC, from_gatt, from_phd, payloads
from edge.devices.decode.phd import configs

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=UTC)
STAMP = DateTime(2026, 10, 10, 8, 30, 0)


def ingest(readings):
    rows = payloads(readings, hdt_id="hdt-0123456789ab", device_id="dev-1", received=NOW)
    index = field_index()
    return [harmonise(raw_from_payload(row), index) for row in rows]


def wire(module, m):
    return from_gatt(gatt.decode(module.UUID, module.encode(m)))


def test_gatt_readings_harmonise_into_twin_fields():
    readings = [
        *wire(heart_rate, heart_rate.HeartRateMeasurement(72)),
        *wire(blood_pressure, blood_pressure.BloodPressureMeasurement(
            16.0, 10.7, 12.4, kpa=True, time_stamp=STAMP, pulse_rate=70.0)),
        *wire(glucose, glucose.GlucoseMeasurement(3, STAMP, 5, 0.00099)),
        *wire(plx, plx.PlxContinuousMeasurement(plx.SpO2PR(97.0, 66.0))),
        *wire(weight, weight.WeightMeasurement(154.0, True, STAMP, None, 22.1, 70.0)),
        *wire(temperature, temperature.TemperatureMeasurement(37.2, time_stamp=STAMP)),
    ]
    got = {(h.ref.field.name, h.unit): h.value for h in ingest(readings)}
    assert got[("sbp", "mm[Hg]")] == pytest.approx(120.0, abs=0.5)
    assert got[("glucose", "mmol/L")] == pytest.approx(5.495, abs=0.01)
    assert got[("spo2", "%")] == 97.0
    assert got[("weight", "kg")] == pytest.approx(69.85, abs=0.01)
    assert got[("height", "cm")] == pytest.approx(177.8, abs=0.01)
    assert got[("bmi", "kg/m2")] == pytest.approx(22.1)
    assert got[("temperature", "Cel")] == pytest.approx(37.2)
    glucose_reading = next(r for r in readings if r.loinc == "15074-8")
    assert glucose_reading.time == datetime(2026, 10, 10, 8, 35)


def test_phd_readings_carry_mdc_alt_codes():
    report = phd.scan_report(configs.BLOOD_PRESSURE, {1: [120, 80, 93], 2: 64},
                             datetime(2026, 10, 10, 8, 0))
    readings = from_phd(phd.decode_scan(report, configs.BLOOD_PRESSURE))
    assert [r.loinc for r in readings] == ["8480-6", "8462-4", "8478-0", "8867-4"]
    sbp = ingest(readings)[0]
    assert sbp.raw.alt_codes[0].system == SYSTEMS["mdc"]
    assert sbp.raw.alt_codes[0].code == "150021"
    spiro = phd.scan_report(configs.SPIROMETER, {1: 410, 2: 2.85})
    assert [(h.ref.field.name, h.value, h.unit) for h in
            ingest(from_phd(phd.decode_scan(spiro, configs.SPIROMETER)))] == [
        ("pef", 410.0, "L/min"), ("fev1", 2.85, "L")]


def test_glucometer_mg_per_dl_becomes_mmol_per_l():
    report = phd.scan_report(configs.GLUCOMETER, {1: 99})
    (reading,) = from_phd(phd.decode_scan(report, configs.GLUCOMETER))
    assert (reading.unit, reading.value) == ("mmol/L", pytest.approx(5.495, abs=0.01))


def test_unavailable_values_are_left_out():
    m = plx.PlxContinuousMeasurement(plx.SpO2PR(math.nan, 66.0))
    assert [r.loinc for r in from_gatt(m)] == ["8867-4"]


def test_every_mapped_code_is_verified():
    for loinc in set(LOINC_OF_MDC.values()):
        assert loinc in table("loinc"), loinc
    for term in LOINC_OF_MDC:
        assert str(term.cf) in table("mdc")
