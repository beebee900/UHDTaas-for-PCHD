"""Step 3 of the pipeline: codes, units and FHIR resources (design 04, 4.3.1).

An incoming value is matched to its twin field by any of its codes, converted to the
field's UCUM unit, and given the field's canonical code with the others kept as
`alt_codes`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from fhir.resources.R4B.observation import Observation

from ahdt.ingest.fields import FieldIndex, FieldRef
from atra import units
from atra.codes import SYSTEMS
from atra.contracts import Code, Waveform

CONSENT_TAG_SYSTEM = "urn:atra:consent"


@dataclass
class RawObservation:
    """A value as it arrives, before harmonisation.

    The subject is either `hdt_id` or a direct identifier `(system, value)`, which the
    pseudonymisation step replaces.
    """

    record_id: str
    code: Code
    value: float | int | bool | str | Waveform
    unit: str
    effective_time: datetime
    source: str = "device"
    hdt_id: str | None = None
    identifier: tuple[str, str] | None = None
    alt_codes: list[Code] = field(default_factory=list)
    device_id: str | None = None
    sim_time: float | None = None
    version: int = 1
    idempotency_key: str | None = None


@dataclass
class Harmonised:
    raw: RawObservation
    ref: FieldRef
    value: float | int | bool | str | Waveform
    unit: str


class HarmoniseError(ValueError):
    pass


def harmonise(raw: RawObservation, index: FieldIndex) -> Harmonised:
    ref = index.resolve(raw.code)
    for alt in raw.alt_codes:
        ref = ref or index.resolve(alt)
    if ref is None:
        raise HarmoniseError(f"code {raw.code.system}|{raw.code.code} belongs to no twin field")
    target = ref.field.ucum
    value = raw.value
    if isinstance(value, int | float) and not isinstance(value, bool) and raw.unit != target:
        substance = ref.field.name if ref.field.name in units.MOLAR_MASS else None
        try:
            value = units.convert(float(value), raw.unit, target, substance=substance)
        except units.UnitError as exc:
            raise HarmoniseError(f"unit {raw.unit} does not convert to {target}: {exc}") from exc
        return Harmonised(raw, ref, value, target)
    unit = target if isinstance(value, Waveform) or raw.unit == target else raw.unit
    return Harmonised(raw, ref, value, unit)


def _coding(c: Code) -> dict[str, Any]:
    out: dict[str, Any] = {"system": c.system, "code": c.code}
    if c.display:
        out["display"] = c.display
    return out


def fhir_observation(h: Harmonised, *, hdt_id: str, record_id: str,
                     consent_tag: str) -> dict[str, Any]:
    """A FHIR R4B Observation of one harmonised scalar value, validated by fhir.resources."""
    codings = [_coding(h.ref.code), *(_coding(c) for c in h.ref.alt_codes)]
    body: dict[str, Any] = {
        "resourceType": "Observation", "id": record_id, "status": "final",
        "meta": {"tag": [{"system": CONSENT_TAG_SYSTEM, "code": consent_tag}]},
        "code": {"coding": codings, "text": h.ref.field.name},
        "subject": {"reference": f"Patient/{hdt_id}"},
        "effectiveDateTime": h.raw.effective_time.isoformat(),
    }
    if h.raw.device_id:
        body["device"] = {"display": h.raw.device_id}
    v = h.value
    if isinstance(v, bool):
        body["valueBoolean"] = v
    elif isinstance(v, int | float):
        body["valueQuantity"] = {"value": v, "unit": h.unit, "system": SYSTEMS["ucum"],
                                 "code": h.unit}
    elif isinstance(v, str):
        body["valueString"] = v
    else:
        raise HarmoniseError("waveforms are stored as arrays, not as FHIR Observations")
    resource: Mapping[str, Any] = Observation.model_validate(body).model_dump(
        mode="json", exclude_none=True)
    return dict(resource)
