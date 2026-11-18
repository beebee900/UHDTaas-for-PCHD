"""HL7 v2 to FHIR R4 for the p0 path (design 05, 5.3): ORU^R01 → DiagnosticReport and
Observation, ADT^A01/A03 → Encounter, RDE^O11 → MedicationRequest.

Messages are split and parsed by `python-hl7`; fields are read as text with the message's
own encoding characters. The Mirth channels (`apdt/integration/mirth/hl7v2_to_fhir.js`) run
the same mapping, so both paths give the same resources.

Field positions follow the HL7 v2.5 segment definitions (Caristix HL7 v2.5 reference:
PID-3, PV1-2/19/44/45, ORC-1/2/9/12, OBR-2/3/4/7/22/24/25, OBX-1/2/3/5/6/8/11/14,
RXE-2/3/5, RXR-1). Status codes follow the HL7 v2-to-FHIR IG concept maps
`table-hl70085-to-observation-status`, `table-hl70123-queries-to-diagnostic-report-status`,
`table-hl70119-to-request-status`, `table-hl70004-to-v3-actcode` and
`table-hl70078-to-v3-observationinterpretation`. A timestamp without an offset is read as
UTC, as in `ahdt.ingest.batch`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import hl7
from fhir.resources.R4B.diagnosticreport import DiagnosticReport
from fhir.resources.R4B.encounter import Encounter
from fhir.resources.R4B.medicationrequest import MedicationRequest
from fhir.resources.R4B.observation import Observation

from ahdt.ingest.batch import HL7_SYSTEMS
from apdt.records.episodes import PATIENT_SYSTEM
from atra.codes import SYSTEMS

CODING_SYSTEMS: Mapping[str, str] = {**HL7_SYSTEMS, "WC": SYSTEMS["atc"],
                                     "UCUM": SYSTEMS["ucum"]}
"""HL7 table 0396 coding-system ids → FHIR system URIs (WC is the WHO ATC)."""
UNKNOWN_SYSTEM = "urn:atra:hl7v2:coding:"
AUTHORITY_SYSTEM = "urn:atra:hl7v2:authority:"
ATRA_AUTHORITY = "ATRA"
PLACER_SYSTEM = "urn:atra:hl7v2:placer"
FILLER_SYSTEM = "urn:atra:hl7v2:filler"
V2_0074 = "http://terminology.hl7.org/CodeSystem/v2-0074"
V2_0162 = "http://terminology.hl7.org/CodeSystem/v2-0162"
OBS_CATEGORY = "http://terminology.hl7.org/CodeSystem/observation-category"
INTERPRETATION = "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation"
ACT_CODE = "http://terminology.hl7.org/CodeSystem/v3-ActCode"

OBSERVATION_STATUS = {"A": "amended", "C": "corrected", "D": "entered-in-error", "F": "final",
                      "P": "preliminary", "X": "cancelled", "W": "entered-in-error"}
REPORT_STATUS = {"O": "registered", "I": "registered", "S": "registered", "P": "preliminary",
                 "C": "corrected", "R": "partial", "F": "final", "X": "cancelled"}
REQUEST_STATUS = {"AF": "active", "CA": "active", "CR": "revoked", "DC": "revoked",
                  "DF": "revoked", "DR": "revoked", "FU": "completed", "HD": "active",
                  "HR": "on-hold", "NW": "active", "OC": "revoked", "OD": "revoked",
                  "OH": "on-hold", "OK": "active", "PR": "active", "PY": "active",
                  "RL": "active", "RO": "active", "RQ": "active"}
PATIENT_CLASS = {"E": "EMER", "I": "IMP", "O": "AMB", "P": "PRENC", "R": "R", "B": "B",
                 "C": "C", "N": "N", "U": "U"}
INTERPRETATION_CODES = frozenset({
    "<", ">", "A", "AA", "B", "CAR", "D", "DET", "E", "EX", "EXP", "H", "HH", "HU", "I", "IE",
    "IND", "L", "LL", "LU", "MS", "N", "NCL", "ND", "NEG", "NR", "NS", "POS", "R", "RR", "S",
    "SDD", "SYN-R", "SYN-S", "U", "VS", "UNE", "W", "WR"})
"""Table 0078 codes with an identical v3 ObservationInterpretation code."""
COMPARATORS = frozenset({"<", "<=", ">=", ">"})
_ID_CHARS = re.compile(r"[^A-Za-z0-9\-.]")


class HL7MappingError(ValueError):
    pass


@dataclass
class Mapped:
    """The FHIR resources of one HL7 v2 message, with the identifiers needed to file them."""

    message_type: str
    control_id: str
    patient: tuple[str, str]
    resources: list[dict[str, Any]] = field(default_factory=list)
    trigger: str = ""


def fhir_id(value: str) -> str:
    return _ID_CHARS.sub("-", value)[:64]


def hl7_time(value: str) -> str:
    """HL7 TS (YYYYMMDD[HHMM[SS[.S+]]][+/-ZZZZ]) → ISO 8601."""
    m = re.fullmatch(r"(\d{8})(\d{4})?(\d{2})?(?:\.\d+)?([+-]\d{4})?", value.strip())
    if not m:
        raise HL7MappingError(f"not an HL7 timestamp: {value!r}")
    date, hm, sec, zone = m.groups()
    t = datetime.strptime(date + (hm or "0000") + (sec or "00"), "%Y%m%d%H%M%S")
    tz = UTC
    if zone:
        sign = 1 if zone[0] == "+" else -1
        tz = timezone(sign * timedelta(hours=int(zone[1:3]), minutes=int(zone[3:5])))
    return t.replace(tzinfo=tz).isoformat()


class _Message:
    def __init__(self, text: str) -> None:
        self.msg = hl7.parse(text)
        # MSH-2 holds the encoding characters: component, repetition, escape, subcomponent.
        self.comp, self.rep = text[4], text[5]

    def segments(self) -> list[Any]:
        return list(self.msg)

    def get(self, seg: Any, number: int, component: int = 1) -> str:
        """Field `number`, first repetition, component `component` (1-based), as text."""
        try:
            text = str(seg[number])
        except IndexError:
            return ""
        parts = text.split(self.rep)[0].split(self.comp)
        return parts[component - 1] if component <= len(parts) else ""

    def coding(self, seg: Any, number: int) -> dict[str, Any] | None:
        code = self.get(seg, number, 1)
        if not code:
            return None
        sid = self.get(seg, number, 3)
        out: dict[str, Any] = {"system": CODING_SYSTEMS.get(sid, UNKNOWN_SYSTEM + sid),
                               "code": code}
        if self.get(seg, number, 2):
            out["display"] = self.get(seg, number, 2)
        return out


def _concept(coding: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {"coding": [coding]}
    if coding.get("display"):
        out["text"] = coding["display"]
    return out


def _subject(patient: tuple[str, str]) -> dict[str, Any]:
    return {"identifier": {"system": patient[0], "value": patient[1]}}


def _validated(model: Any, body: dict[str, Any]) -> dict[str, Any]:
    return dict(model.model_validate(body).model_dump(mode="json", exclude_none=True))


def _observation(m: _Message, obx: Any, control: str, index: int, patient: tuple[str, str],
                 when_default: str) -> dict[str, Any]:
    code = m.coding(obx, 3)
    if code is None:
        raise HL7MappingError(f"OBX {index} has no OBX-3 code")
    set_id = m.get(obx, 1) or str(index)
    body: dict[str, Any] = {
        "resourceType": "Observation", "id": fhir_id(f"obs-{control}-{set_id}"),
        "status": OBSERVATION_STATUS.get(m.get(obx, 11), "unknown"),
        "category": [{"coding": [{"system": OBS_CATEGORY, "code": "laboratory"}]}],
        "code": _concept(code), "subject": _subject(patient)}
    when = m.get(obx, 14) or when_default
    if when:
        body["effectiveDateTime"] = hl7_time(when)
    vtype, unit = m.get(obx, 2), m.get(obx, 6)
    if vtype == "NM" and m.get(obx, 5):
        body["valueQuantity"] = _quantity(float(m.get(obx, 5)), unit)
    elif vtype == "SN" and m.get(obx, 5, 2):
        q = _quantity(float(m.get(obx, 5, 2)), unit)
        if m.get(obx, 5, 1) in COMPARATORS:
            q["comparator"] = m.get(obx, 5, 1)
        body["valueQuantity"] = q
    elif vtype in ("CE", "CWE") and m.coding(obx, 5):
        body["valueCodeableConcept"] = _concept(m.coding(obx, 5) or {})
    elif m.get(obx, 5):
        body["valueString"] = str(obx[5])
    flag = m.get(obx, 8)
    if flag in INTERPRETATION_CODES:
        body["interpretation"] = [{"coding": [{"system": INTERPRETATION, "code": flag}]}]
    return _validated(Observation, body)


def _quantity(value: float, unit: str) -> dict[str, Any]:
    q: dict[str, Any] = {"value": value}
    if unit:
        q.update(unit=unit, system=SYSTEMS["ucum"], code=unit)
    return q


def _patient(m: _Message) -> tuple[str, str]:
    pid = m.msg.segment("PID")
    value, authority = m.get(pid, 3, 1), m.get(pid, 3, 4)
    if not value:
        raise HL7MappingError("PID-3 has no identifier")
    if authority == ATRA_AUTHORITY:
        return PATIENT_SYSTEM, value
    return AUTHORITY_SYSTEM + (authority or "unknown"), value


def _oru(m: _Message, out: Mapped) -> None:
    report: dict[str, Any] | None = None
    reports: list[dict[str, Any]] = []
    obr_when = ""
    index = 0
    for seg in m.segments():
        kind = str(seg[0])
        if kind == "OBR":
            obr_when = m.get(seg, 7)
            report = {"resourceType": "DiagnosticReport",
                      "id": fhir_id(f"dr-{out.control_id}-{m.get(seg, 1) or len(reports) + 1}"),
                      "status": REPORT_STATUS.get(m.get(seg, 25), "unknown"),
                      "category": [{"coding": [{"system": V2_0074,
                                                "code": m.get(seg, 24) or "LAB"}]}],
                      "subject": _subject(out.patient), "result": []}
            if m.coding(seg, 4):
                report["code"] = _concept(m.coding(seg, 4) or {})
            if m.get(seg, 2):
                report["basedOn"] = [{"type": "ServiceRequest",
                                      "identifier": {"system": PLACER_SYSTEM,
                                                     "value": m.get(seg, 2)}}]
            if m.get(seg, 3):
                report["identifier"] = [{"system": FILLER_SYSTEM, "value": m.get(seg, 3)}]
            if obr_when:
                report["effectiveDateTime"] = hl7_time(obr_when)
            if m.get(seg, 22):
                report["issued"] = hl7_time(m.get(seg, 22))
            reports.append(report)
        elif kind == "OBX":
            index += 1
            obs = _observation(m, seg, out.control_id, index, out.patient, obr_when)
            out.resources.append(obs)
            if report is not None:
                report["result"].append({"reference": f"Observation/{obs['id']}"})
                report.setdefault("code", obs["code"])
    for r in reports:
        out.resources.append(_validated(DiagnosticReport, r))


def _adt(m: _Message, out: Mapped) -> None:
    pv1 = m.msg.segment("PV1")
    visit = m.get(pv1, 19) or out.control_id
    body: dict[str, Any] = {
        "resourceType": "Encounter", "id": fhir_id(f"enc-{visit}"),
        "status": "finished" if out.trigger == "A03" else "in-progress",
        "class": {"system": ACT_CODE, "code": PATIENT_CLASS.get(m.get(pv1, 2), "U")},
        "subject": _subject(out.patient),
        "identifier": [{"system": PLACER_SYSTEM, "value": visit}]}
    period = {}
    if m.get(pv1, 44):
        period["start"] = hl7_time(m.get(pv1, 44))
    if m.get(pv1, 45):
        period["end"] = hl7_time(m.get(pv1, 45))
    if period:
        body["period"] = period
    out.resources.append(_validated(Encounter, body))


def _rde(m: _Message, out: Mapped) -> None:
    orc: Any = None
    count = 0
    pending: dict[str, Any] | None = None
    for seg in m.segments():
        kind = str(seg[0])
        if kind == "ORC":
            orc = seg
        elif kind == "RXE":
            if pending is not None:
                out.resources.append(_validated(MedicationRequest, pending))
            count += 1
            pending = _medication_request(m, orc, seg, out, count)
        elif kind == "RXR" and pending is not None:
            route = m.coding(seg, 1)
            if route is not None:
                if route["system"] == UNKNOWN_SYSTEM + "HL70162":
                    route["system"] = V2_0162
                pending["dosageInstruction"][0]["route"] = _concept(route)
    if pending is not None:
        out.resources.append(_validated(MedicationRequest, pending))


def _medication_request(m: _Message, orc: Any, rxe: Any, out: Mapped,
                        count: int) -> dict[str, Any]:
    medication = m.coding(rxe, 2)
    if medication is None:
        raise HL7MappingError("RXE-2 has no give code")
    placer = m.get(orc, 2) if orc is not None else ""
    body: dict[str, Any] = {
        "resourceType": "MedicationRequest",
        "id": fhir_id(f"mr-{placer or out.control_id}-{count}"),
        "status": REQUEST_STATUS.get(m.get(orc, 1) if orc is not None else "", "unknown"),
        "intent": "order", "medicationCodeableConcept": _concept(medication),
        "subject": _subject(out.patient), "dosageInstruction": [{}]}
    if placer:
        body["identifier"] = [{"system": PLACER_SYSTEM, "value": placer}]
    if orc is not None and m.get(orc, 9):
        body["authoredOn"] = hl7_time(m.get(orc, 9))
    if orc is not None and m.get(orc, 12, 2):
        name = " ".join(p for p in (m.get(orc, 12, 3), m.get(orc, 12, 2)) if p)
        body["requester"] = {"display": name}
    if m.get(rxe, 3):
        body["dosageInstruction"][0]["doseAndRate"] = [
            {"doseQuantity": _quantity(float(m.get(rxe, 3)), m.get(rxe, 5))}]
    return body


def map_message(text: str) -> Mapped:
    """One HL7 v2 message → its FHIR resources (validated with fhir.resources R4B)."""
    text = text.replace("\r\n", "\r").replace("\n", "\r").strip("\r")
    m = _Message(text)
    msh = m.msg.segment("MSH")
    mtype, trigger = m.get(msh, 9, 1), m.get(msh, 9, 2)
    out = Mapped(message_type=f"{mtype}^{trigger}", control_id=m.get(msh, 10),
                 patient=_patient(m), trigger=trigger)
    if mtype == "ORU" and trigger == "R01":
        _oru(m, out)
    elif mtype == "ADT" and trigger in ("A01", "A03"):
        _adt(m, out)
    elif mtype == "RDE" and trigger == "O11":
        _rde(m, out)
    else:
        raise HL7MappingError(f"unsupported message type {out.message_type}")
    return out


def to_bundle(mapped: Mapped) -> dict[str, Any]:
    """A FHIR `collection` Bundle of the mapped resources, the shape the Mirth path posts."""
    return {"resourceType": "Bundle", "type": "collection",
            "identifier": {"system": "urn:atra:hl7v2:control-id", "value": mapped.control_id},
            "entry": [{"resource": r} for r in mapped.resources]}


def split_batch(text: str) -> list[str]:
    """The messages of a batch, one MSH each."""
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    return [p.strip("\r") for p in re.split(r"\r(?=MSH\|)", "\r" + text) if p.strip("\r")]
