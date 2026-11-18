"""Decoded device readings as ingestion payloads (design 03, 3.3).

A reading carries a LOINC code, the UCUM unit it arrived in, and the matching MDC term as an
alternative code. `payload` gives the JSON form read by `ahdt.ingest.pipeline.raw_from_payload`;
the pipeline converts units to the twin field's unit and builds the `ObservationRecord`.

Glucose is the exception to "unit as it arrived": the twin field is LOINC 15074-8, an amount
concentration, so mass concentrations are converted to mmol/L here. Non-finite values (the
medfloat NaN, NRes and infinities) are not readings and are left out.

`CodedReading` carries an explicit code: twin fields without a standard code use
`FIELD_SYSTEM` and the field name, and waveforms carry `{"array", "period_ms"}` as the value.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from atra import units
from atra.codes import table
from atra.contracts import Code
from edge.devices.decode.gatt import blood_pressure, glucose, heart_rate, plx, temperature, weight
from edge.devices.decode.phd import nomenclature as nom
from edge.devices.decode.phd.configs import Measurement
from edge.devices.decode.phd.nomenclature import Nom

HEART_RATE = "8867-4"
SYSTOLIC = "8480-6"
DIASTOLIC = "8462-4"
MEAN_ARTERIAL = "8478-0"
GLUCOSE = "15074-8"
SPO2 = "59408-5"
BODY_WEIGHT = "29463-7"
BODY_HEIGHT = "8302-2"
BMI = "39156-5"
BODY_TEMPERATURE = "8310-5"
PEAK_FLOW = "19935-6"
FEV1 = "20150-9"
FIELD_SYSTEM = "urn:atra:field"

LOINC_OF_MDC: dict[Nom, str] = {
    nom.MDC_PRESS_BLD_NONINV_SYS: SYSTOLIC,
    nom.MDC_PRESS_BLD_NONINV_DIA: DIASTOLIC,
    nom.MDC_PRESS_BLD_NONINV_MEAN: MEAN_ARTERIAL,
    nom.MDC_PULS_RATE_NON_INV: HEART_RATE,
    nom.MDC_PULS_OXIM_PULS_RATE: HEART_RATE,
    nom.MDC_PULS_OXIM_SAT_O2: SPO2,
    nom.MDC_CONC_GLU_CAPILLARY_WHOLEBLOOD: GLUCOSE,
    nom.MDC_MASS_BODY_ACTUAL: BODY_WEIGHT,
    nom.MDC_LEN_BODY_ACTUAL: BODY_HEIGHT,
    nom.MDC_RATIO_MASS_BODY_LEN_SQ: BMI,
    nom.MDC_TEMP_BODY: BODY_TEMPERATURE,
    nom.MDC_FLOW_AWAY_EXP_FORCED_PEAK: PEAK_FLOW,
    nom.MDC_VOL_AWAY_EXP_FORCED_1S: FEV1,
}


@dataclass(frozen=True)
class Reading:
    loinc: str
    value: float
    unit: str
    mdc: Nom | None = None
    time: datetime | None = None

    @property
    def code(self) -> Code:
        return table("loinc").to_code(self.loinc)

    @property
    def alt_codes(self) -> list[Code]:
        return [table("mdc").to_code(str(self.mdc.cf))] if self.mdc else []


@dataclass(frozen=True)
class CodedReading:
    code: Code
    value: float | dict[str, Any]
    unit: str
    time: datetime | None = None
    alt_codes: tuple[Code, ...] = ()


def field_reading(name: str, value: float, unit: str, time: datetime | None = None
                  ) -> list[CodedReading]:
    """A reading of a twin field that has no standard code."""
    if not math.isfinite(value):
        return []
    return [CodedReading(Code(system=FIELD_SYSTEM, code=name), value, unit, time)]


def _reading(loinc: str, value: float | None, unit: str, mdc: Nom | None = None,
             time: datetime | None = None) -> list[Reading]:
    if value is None or not math.isfinite(value):
        return []
    if loinc == GLUCOSE and unit != "mmol/L":
        value = units.convert(value, unit, "mmol/L", substance="glucose")
        unit = "mmol/L"
    return [Reading(loinc, value, unit, mdc, time)]


def from_gatt(m: Any) -> list[Reading]:
    """Readings of one decoded GATT characteristic value."""
    if isinstance(m, heart_rate.HeartRateMeasurement):
        return _reading(HEART_RATE, m.heart_rate, "/min")
    if isinstance(m, blood_pressure.BloodPressureMeasurement):
        t = m.time_stamp.to_datetime() if m.time_stamp else None
        p = "kPa" if m.kpa else "mm[Hg]"
        return [*_reading(SYSTOLIC, m.systolic, p, nom.MDC_PRESS_BLD_NONINV_SYS, t),
                *_reading(DIASTOLIC, m.diastolic, p, nom.MDC_PRESS_BLD_NONINV_DIA, t),
                *_reading(MEAN_ARTERIAL, m.mean_arterial, p, nom.MDC_PRESS_BLD_NONINV_MEAN, t),
                *_reading(HEART_RATE, m.pulse_rate, "/min", nom.MDC_PULS_RATE_NON_INV, t)]
    if isinstance(m, glucose.GlucoseMeasurement):
        base = m.base_time.to_datetime()
        if base is not None and m.time_offset_min:
            base += timedelta(minutes=m.time_offset_min)
        capillary = m.sample_type == glucose.CAPILLARY_WHOLE_BLOOD
        return _reading(GLUCOSE, m.concentration, m.ucum,
                        nom.MDC_CONC_GLU_CAPILLARY_WHOLEBLOOD if capillary else None, base)
    if isinstance(m, plx.PlxContinuousMeasurement):
        return [*_reading(SPO2, m.normal.spo2, "%", nom.MDC_PULS_OXIM_SAT_O2),
                *_reading(HEART_RATE, m.normal.pulse_rate, "/min", nom.MDC_PULS_OXIM_PULS_RATE)]
    if isinstance(m, weight.WeightMeasurement):
        t = m.time_stamp.to_datetime() if m.time_stamp else None
        return [*_reading(BODY_WEIGHT, m.weight, m.weight_ucum, nom.MDC_MASS_BODY_ACTUAL, t),
                *_reading(BMI, m.bmi, "kg/m2", nom.MDC_RATIO_MASS_BODY_LEN_SQ, t),
                *_reading(BODY_HEIGHT, m.height, m.height_ucum, nom.MDC_LEN_BODY_ACTUAL, t)]
    if isinstance(m, temperature.TemperatureMeasurement):
        t = m.time_stamp.to_datetime() if m.time_stamp else None
        return _reading(BODY_TEMPERATURE, m.value, m.ucum, nom.MDC_TEMP_BODY, t)
    raise TypeError(f"no mapping for {type(m).__name__}")


def from_phd(measurements: Iterable[Measurement]) -> list[Reading]:
    """Readings of decoded 11073-20601 scan-report measurements with a known MDC term."""
    out: list[Reading] = []
    for m in measurements:
        unit = nom.UCUM[m.unit]
        for term, value in m.values:
            loinc = LOINC_OF_MDC.get(term)
            if loinc is not None:
                out += _reading(loinc, value, unit, term, m.time)
    return out


def payload(reading: Reading | CodedReading, *, hdt_id: str, device_id: str, received: datetime,
            sim_time: float | None = None) -> dict[str, Any]:
    """The ingestion payload of a reading; `received` stands in for a missing device time."""
    return {
        "code": reading.code.model_dump(),
        "alt_codes": [c.model_dump() for c in reading.alt_codes],
        "value": reading.value,
        "unit": reading.unit,
        "effective_time": (reading.time or received).isoformat(),
        "source": "device",
        "hdt_id": hdt_id,
        "device_id": device_id,
        "sim_time": sim_time,
    }


def payloads(readings: Sequence[Reading | CodedReading], **kwargs: Any) -> list[dict[str, Any]]:
    return [payload(r, **kwargs) for r in readings]
