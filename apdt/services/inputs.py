"""The clinical inputs of an episode as FHIR resources, and back into model inputs.

An episode keeps what is known about the patient as `Observation`, `Condition` and
`MedicationRequest` resources. Observations are coded in one of three systems:

- `KB_SYSTEM`: the code is a kb finding id (`find.*`) or test id (`test.*`) and the value is
  a boolean (present, or positive).
- `MEASURE_SYSTEM`: the code is a measurement field (`temperature`, `sbp`, `creatinine`, ...)
  and the value is a quantity. The code `avpu` carries a string.
- `CONTEXT_SYSTEM`: the code is a patient attribute (`age_years`, `sex`, `weight_kg`,
  `pregnancy`, `hb_genotype`).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apdt.models.context import Observations, Patient

KB_SYSTEM = "https://atra.health/kb"
MEASURE_SYSTEM = "https://atra.health/fhir/CodeSystem/measurement"
CONTEXT_SYSTEM = "https://atra.health/fhir/CodeSystem/patient-context"
_REQUIRED = ("age_years", "sex")


class MissingInputs(ValueError):
    def __init__(self, missing: list[str]) -> None:
        super().__init__("the episode lacks " + ", ".join(missing))
        self.missing = missing


def _observation(system: str, code: str, **value: Any) -> dict[str, Any]:
    return {"resourceType": "Observation", "status": "final",
            "code": {"coding": [{"system": system, "code": code}]}, **value}


def to_resources(patient: Patient, obs: Observations) -> list[dict[str, Any]]:
    """The episode resources that carry `patient` and `obs`."""
    out = [_observation(CONTEXT_SYSTEM, "age_years", valueQuantity={"value": patient.age_years}),
           _observation(CONTEXT_SYSTEM, "sex", valueString=patient.sex),
           _observation(CONTEXT_SYSTEM, "pregnancy", valueString=patient.pregnancy)]
    if patient.weight_kg is not None:
        out.append(_observation(CONTEXT_SYSTEM, "weight_kg",
                                valueQuantity={"value": patient.weight_kg}))
    if patient.hb_genotype:
        out.append(_observation(CONTEXT_SYSTEM, "hb_genotype", valueString=patient.hb_genotype))
    out += [{"resourceType": "Condition",
             "code": {"coding": [{"system": KB_SYSTEM, "code": cond}]}}
            for cond in patient.conditions]
    out += [{"resourceType": "MedicationRequest", "status": "active", "intent": "order",
             "medicationCodeableConcept": {"text": drug}} for drug in patient.medications]
    out += [_observation(KB_SYSTEM, f, valueBoolean=v) for f, v in obs.findings.items()]
    out += [_observation(KB_SYSTEM, t, valueBoolean=v) for t, v in obs.tests.items()]
    out += [_observation(MEASURE_SYSTEM, m, valueQuantity={"value": v})
            for m, v in obs.measurements.items()]
    out.append(_observation(MEASURE_SYSTEM, "avpu", valueString=obs.avpu))
    return out


def _coding(resource: Mapping[str, Any]) -> tuple[str, str] | None:
    for c in resource.get("code", {}).get("coding", []):
        if c.get("system") and c.get("code"):
            return str(c["system"]), str(c["code"])
    return None


def _number(resource: Mapping[str, Any]) -> float | None:
    value = resource.get("valueQuantity", {}).get("value")
    return float(value) if isinstance(value, int | float) else None


def from_resources(resources: Iterable[Mapping[str, Any]], tenant_id: str
                   ) -> tuple[Patient, Observations]:
    """The patient and observations that an episode's resources describe."""
    context: dict[str, Any] = {}
    conditions: list[str] = []
    medications: list[str] = []
    obs = Observations()
    for r in resources:
        kind = r.get("resourceType")
        if kind == "Condition":
            coding = _coding(r)
            if coding and coding[0] == KB_SYSTEM:
                conditions.append(coding[1])
        elif kind == "MedicationRequest":
            name = r.get("medicationCodeableConcept", {}).get("text")
            if name:
                medications.append(str(name).lower())
        elif kind == "Observation":
            coding = _coding(r)
            if coding is None:
                continue
            system, code = coding
            if system == KB_SYSTEM and isinstance(r.get("valueBoolean"), bool):
                (obs.tests if code.startswith("test.") else obs.findings)[code] = r["valueBoolean"]
            elif system == MEASURE_SYSTEM and code == "avpu" and "valueString" in r:
                obs.avpu = str(r["valueString"])
            elif system == MEASURE_SYSTEM and (value := _number(r)) is not None:
                obs.measurements[code] = value
            elif system == CONTEXT_SYSTEM:
                context[code] = r["valueString"] if "valueString" in r else _number(r)
    missing = [k for k in _REQUIRED if context.get(k) is None]
    if missing:
        raise MissingInputs(missing)
    patient = Patient(
        age_years=float(context["age_years"]), sex=context["sex"],
        weight_kg=context.get("weight_kg"),
        pregnancy=context.get("pregnancy") or "none", hb_genotype=context.get("hb_genotype"),
        conditions=tuple(conditions), medications=tuple(medications), tenant_id=tenant_id)
    return patient, obs
