"""DICOM SR (TID 1500 measurement report) → FHIR DiagnosticReport for the p0 path
(design 05, 5.3).

`highdicom.sr.srread` reads the SR. Each measurement group (DCM 125007) gives one
Observation per numeric item (valueQuantity in the item's UCUM unit) and per coded item
(valueCodeableConcept). The report is final when the SR is verified and complete.
"""

from __future__ import annotations

import base64
import hashlib
import io
from typing import Any

import highdicom as hd
from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.observation import Observation

from apdt.integration.hl7v2 import (
    ATRA_AUTHORITY,
    AUTHORITY_SYSTEM,
    OBS_CATEGORY,
    V2_0074,
    Mapped,
)
from apdt.records.episodes import PATIENT_SYSTEM
from atra.codes import SYSTEMS

SCHEMES = {"SCT": SYSTEMS["snomed"], "LN": SYSTEMS["loinc"], "UCUM": SYSTEMS["ucum"],
           "DCM": "http://dicom.nema.org/resources/ontology/DCM", "RADLEX": SYSTEMS["radlex"]}
DICOM_UID = "urn:dicom:uid"
MEASUREMENT_GROUP = ("DCM", "125007")
PROCEDURE_REPORTED = ("DCM", "121058")


def _code(item: Any) -> dict[str, Any]:
    scheme = str(item.CodingSchemeDesignator)
    return {"system": SCHEMES.get(scheme, f"urn:atra:dicom:scheme:{scheme}"),
            "code": str(item.CodeValue), "display": str(item.CodeMeaning)}


def _concept(item: Any) -> dict[str, Any]:
    c = _code(item)
    return {"coding": [c], "text": c["display"]}


def _key(item: Any) -> tuple[str, str]:
    cn = item.ConceptNameCodeSequence[0]
    return str(cn.CodingSchemeDesignator), str(cn.CodeValue)


def _walk(items: Any) -> list[Any]:
    out = []
    for item in items:
        out.append(item)
        if "ContentSequence" in item:
            out.extend(_walk(item.ContentSequence))
    return out


def _when(date: str, time: str) -> str:
    t = (time or "000000").split(".")[0].ljust(6, "0")
    return f"{date[:4]}-{date[4:6]}-{date[6:8]}T{t[:2]}:{t[2:4]}:{t[4:6]}+00:00"


def decode(body: bytes) -> bytes:
    """A DICOM Part 10 file, from raw bytes or from base64 text (the Mirth path)."""
    if body[128:132] == b"DICM":
        return body
    return base64.b64decode(body, validate=False)


def map_sr(data: bytes) -> Mapped:
    sr = hd.sr.srread(io.BytesIO(decode(data)))
    sop = str(sr.SOPInstanceUID)
    tag = hashlib.sha1(sop.encode()).hexdigest()[:16]
    issuer = str(getattr(sr, "IssuerOfPatientID", "") or "")
    patient = ((PATIENT_SYSTEM if issuer == ATRA_AUTHORITY else AUTHORITY_SYSTEM
                + (issuer or "unknown")), str(sr.PatientID))
    subject = {"identifier": {"system": patient[0], "value": patient[1]}}
    when = _when(str(sr.ContentDate), str(getattr(sr, "ContentTime", "")))
    out = Mapped(message_type="DICOM^SR", control_id=sop, patient=patient)
    report: dict[str, Any] = {
        "resourceType": "DiagnosticReport", "id": f"dr-sr-{tag}",
        "status": ("final" if sr.VerificationFlag == "VERIFIED"
                   and sr.CompletionFlag == "COMPLETE" else "preliminary"),
        "category": [{"coding": [{"system": V2_0074, "code": "RAD"}]}],
        "code": _concept(sr.ConceptNameCodeSequence[0]), "subject": subject,
        "effectiveDateTime": when,
        "identifier": [{"system": DICOM_UID, "value": f"urn:oid:{sop}"}],
        "imagingStudy": [{"type": "ImagingStudy", "identifier": {
            "system": DICOM_UID, "value": f"urn:oid:{sr.StudyInstanceUID}"}}],
        "result": []}
    items = _walk(sr.ContentSequence)
    for item in items:
        if _key(item) == PROCEDURE_REPORTED and item.ValueType == "CODE":
            report["code"] = _concept(item.ConceptCodeSequence[0])
    n = 0
    for group in (i for i in items if i.ValueType == "CONTAINER"
                  and _key(i) == MEASUREMENT_GROUP):
        for item in group.get("ContentSequence", []):
            body: dict[str, Any] = {
                "resourceType": "Observation", "status": report["status"],
                "category": [{"coding": [{"system": OBS_CATEGORY, "code": "imaging"}]}],
                "code": _concept(item.ConceptNameCodeSequence[0]), "subject": subject,
                "effectiveDateTime": when}
            if item.ValueType == "NUM":
                mv = item.MeasuredValueSequence[0]
                unit = mv.MeasurementUnitsCodeSequence[0]
                body["valueQuantity"] = {"value": float(mv.NumericValue),
                                         "unit": str(unit.CodeValue),
                                         "system": SYSTEMS["ucum"], "code": str(unit.CodeValue)}
            elif item.ValueType == "CODE":
                body["valueCodeableConcept"] = _concept(item.ConceptCodeSequence[0])
            else:
                continue
            n += 1
            body["id"] = f"obs-sr-{tag}-{n}"
            out.resources.append(dict(Observation.model_validate(body).model_dump(
                mode="json", exclude_none=True)))
            report["result"].append({"reference": f"Observation/{body['id']}"})
    out.resources.append(dict(DiagnosticReport.model_validate(report).model_dump(
        mode="json", exclude_none=True)))
    return out
