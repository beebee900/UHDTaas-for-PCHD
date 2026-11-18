"""The clinical record of an episode: what clinicians enter by hand.

The medical officer records the diagnosis made (`Condition`), the pharmacist records what was
dispensed (`MedicationDispense`) and the nurse records the medication given
(`MedicationAdministration`) or the care carried out (`Procedure`). Each resource carries a
`meta.tag` in `RECORD_TAG` so the record can be told apart from the intake resources, and it
does not change the reasoner's inputs.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from atra import contracts as c

RECORD_TAG = "https://atra.health/fhir/CodeSystem/clinical-record"
PROPOSAL_EXT = f"{RECORD_TAG}/proposal"
Kind = Literal["diagnosis", "dispense", "administration"]


def _base(kind: Kind, actor: c.Actor, at: datetime) -> dict[str, Any]:
    return {"meta": {"tag": [{"system": RECORD_TAG, "code": kind}],
                     "lastUpdated": at.isoformat()},
            "extension": [{"url": f"{RECORD_TAG}/recorder",
                           "valueString": f"{actor.role}|{actor.id}"}]}


def _note(text: str | None, actor: c.Actor, at: datetime) -> list[dict[str, Any]]:
    return [{"text": text, "authorString": actor.id, "time": at.isoformat()}] if text else []


def diagnosis_resource(body: c.DiagnosisEntry, hdt_id: str, actor: c.Actor,
                       at: datetime | None = None) -> dict[str, Any]:
    at = at or datetime.now(UTC)
    resource = {
        "resourceType": "Condition", **_base("diagnosis", actor, at),
        "clinicalStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "code": "active"}]},
        "verificationStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
            "code": body.status}]},
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-category",
            "code": "encounter-diagnosis"}]}],
        "code": {"text": body.condition},
        "subject": {"reference": f"Patient/{hdt_id}"},
        "recordedDate": at.isoformat(),
        "recorder": {"display": actor.id},
        "note": _note(body.basis, actor, at)}
    if body.recommendation_id:
        resource["extension"].append({"url": PROPOSAL_EXT,
                                      "valueString": body.recommendation_id})
    return resource


def dispense_resource(body: c.DispenseEntry, hdt_id: str, actor: c.Actor,
                      at: datetime | None = None) -> dict[str, Any]:
    at = at or datetime.now(UTC)
    resource = {
        "resourceType": "MedicationDispense", **_base("dispense", actor, at),
        "status": "completed",
        "medicationCodeableConcept": {"text": body.medication},
        "subject": {"reference": f"Patient/{hdt_id}"},
        "performer": [{"actor": {"display": actor.id}}],
        "quantity": {"unit": body.quantity},
        "whenHandedOver": at.isoformat(),
        "dosageInstruction": [{"text": body.dose}],
        "note": _note(body.notes, actor, at)}
    if body.days_supply is not None:
        resource["daysSupply"] = {"value": body.days_supply, "unit": "days",
                                  "system": "http://unitsofmeasure.org", "code": "d"}
    return resource


def administration_resource(body: c.AdministrationEntry, hdt_id: str, actor: c.Actor,
                            at: datetime | None = None) -> dict[str, Any]:
    at = at or datetime.now(UTC)
    given = (body.given_at or at).isoformat()
    base = {**_base("administration", actor, at), "status": "completed",
            "subject": {"reference": f"Patient/{hdt_id}"},
            "performer": [{"actor": {"display": actor.id}}],
            "note": _note(body.notes, actor, at)}
    if body.kind == "care":
        return {"resourceType": "Procedure", **base, "code": {"text": body.item},
                "performedDateTime": given}
    dosage: dict[str, Any] = {}
    if body.dose:
        dosage["text"] = body.dose
    if body.route:
        dosage["route"] = {"text": body.route}
    return {"resourceType": "MedicationAdministration", **base,
            "medicationCodeableConcept": {"text": body.item},
            "effectiveDateTime": given, **({"dosage": dosage} if dosage else {})}


def kind_of(resource: Mapping[str, Any]) -> Kind | None:
    for tag in resource.get("meta", {}).get("tag", []):
        if tag.get("system") == RECORD_TAG and tag.get("code") in (
                "diagnosis", "dispense", "administration"):
            code: Kind = tag["code"]
            return code
    return None


def _recorder(resource: Mapping[str, Any]) -> c.Actor:
    for ext in resource.get("extension", []):
        if ext.get("url") == f"{RECORD_TAG}/recorder":
            role, _, actor_id = str(ext["valueString"]).partition("|")
            return c.Actor(id=actor_id, role=role)
    return c.Actor(id="unknown", role="unknown")


def _proposal(resource: Mapping[str, Any]) -> str | None:
    return next((str(e["valueString"]) for e in resource.get("extension", [])
                 if e.get("url") == PROPOSAL_EXT), None)


def _notes(resource: Mapping[str, Any]) -> list[str]:
    return [str(n["text"]) for n in resource.get("note", []) if n.get("text")]


def entry_of(resource: Mapping[str, Any]) -> c.ClinicalEntry | None:
    """The clinical record entry that `resource` stores, or None for any other resource."""
    kind = kind_of(resource)
    if kind is None:
        return None
    rtype = resource["resourceType"]
    details: list[str]
    if rtype == "Condition":
        status = resource["verificationStatus"]["coding"][0]["code"]
        title = str(resource["code"]["text"])
        details = [status.capitalize(),
                   "From the APDT proposal" if _proposal(resource)
                   else "The clinician's own diagnosis"]
    elif rtype == "MedicationDispense":
        title = str(resource["medicationCodeableConcept"]["text"])
        details = [resource["dosageInstruction"][0]["text"],
                   f"Quantity {resource['quantity']['unit']}"]
        if "daysSupply" in resource:
            details.append(f"{resource['daysSupply']['value']} days")
    elif rtype == "MedicationAdministration":
        title = str(resource["medicationCodeableConcept"]["text"])
        dosage = resource.get("dosage", {})
        details = ["Medication given"] + [str(v) for v in (
            dosage.get("text"), dosage.get("route", {}).get("text")) if v]
    else:
        title = str(resource["code"]["text"])
        details = ["Care given"]
    recorded_at = datetime.fromisoformat(resource["meta"]["lastUpdated"])
    return c.ClinicalEntry(entry_id=str(resource["id"]), kind=kind, title=title,
                           details=details + _notes(resource), recorded_by=_recorder(resource),
                           recorded_at=recorded_at, resource=dict(resource))


def entries(resources: Iterable[Mapping[str, Any]]) -> list[c.ClinicalEntry]:
    """The clinical record entries among an episode's resources, newest first."""
    found = [e for r in resources if (e := entry_of(r)) is not None]
    return sorted(found, key=lambda e: e.recorded_at, reverse=True)
