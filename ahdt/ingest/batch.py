"""Batch import (`POST /v1/import`): FHIR Bundle, HL7 v2 batch, CSV, DICOM and VCF
(design 04, 4.3.1 step 1).

Observation-shaped formats become `RawObservation`s for the pipeline. DICOM and VCF are
stored whole after their patient identifiers are replaced by the `hdt_id`.
"""

from __future__ import annotations

import contextlib
import csv
import gzip
import hashlib
import io
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import hl7
import pydicom

from ahdt.ingest.harmonise import RawObservation
from ahdt.ingest.pipeline import IngestPipeline, IngestResult, raw_from_payload
from atra.codes import SYSTEMS
from atra.contracts import Code
from atra.ids import is_hdt_id, new_record_id

HL7_SYSTEMS = {"LN": SYSTEMS["loinc"], "SCT": SYSTEMS["snomed"], "MDC": SYSTEMS["mdc"]}
GENOMICS_BUCKET = "ahdt-genomics"
IMAGING_BUCKET = "ahdt-imaging"
FHIR_PATIENT_SYSTEM = "urn:atra:import:fhir-patient"


def _parse_time(value: str) -> datetime:
    t = datetime.fromisoformat(value)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def from_fhir_bundle(bundle: Mapping[str, Any]) -> list[RawObservation]:
    """Observation entries of a Bundle. A subject that is not an hdt_id is pseudonymised
    through the Patient's first identifier in the same Bundle, else its resource id."""
    resources = [e["resource"] for e in bundle.get("entry", []) if "resource" in e]
    patients: dict[str, tuple[str, str]] = {}
    for r in resources:
        if r.get("resourceType") == "Patient":
            ident = (r.get("identifier") or [{}])[0]
            if ident.get("value"):
                patients[r["id"]] = (str(ident.get("system", FHIR_PATIENT_SYSTEM)),
                                     str(ident["value"]))
            else:
                patients[r["id"]] = (FHIR_PATIENT_SYSTEM, str(r["id"]))
    out = []
    for r in resources:
        if r.get("resourceType") != "Observation":
            continue
        ref = str(r.get("subject", {}).get("reference", "")).removeprefix("Patient/")
        codings = r.get("code", {}).get("coding", [])
        if not codings:
            continue
        codes = [Code(system=c["system"], code=c["code"], display=c.get("display"))
                 for c in codings]
        if "valueQuantity" in r:
            value: Any = r["valueQuantity"]["value"]
            unit = r["valueQuantity"].get("code") or r["valueQuantity"].get("unit", "1")
        elif "valueBoolean" in r:
            value, unit = r["valueBoolean"], "1"
        elif "valueString" in r:
            value, unit = r["valueString"], "1"
        else:
            continue
        when = r.get("effectiveDateTime") or r.get("issued")
        out.append(RawObservation(
            record_id=str(r.get("id") or new_record_id()), code=codes[0], alt_codes=codes[1:],
            value=value, unit=str(unit), effective_time=_parse_time(str(when)), source="import",
            hdt_id=ref if is_hdt_id(ref) else None,
            identifier=None if is_hdt_id(ref) else patients.get(ref, (FHIR_PATIENT_SYSTEM, ref))))
    return out


def _f(seg: Any, field: int, component: int | None = None) -> str:
    try:
        return str(seg[field]) if component is None else str(seg[field][0][component])
    except IndexError:
        return ""


def _hl7_time(value: str) -> datetime:
    digits = value.split("+")[0].split("-")[0]
    fmt = {8: "%Y%m%d", 12: "%Y%m%d%H%M", 14: "%Y%m%d%H%M%S"}[len(digits)]
    return datetime.strptime(digits, fmt).replace(tzinfo=UTC)


def from_hl7v2(text: str) -> list[RawObservation]:
    """OBX results of ORU messages; a batch may hold several messages, one MSH each."""
    text = text.replace("\r\n", "\r").replace("\n", "\r")
    messages = ["MSH" + m for m in text.split("MSH")[1:]]
    out = []
    for m in messages:
        msg = hl7.parse(m.strip("\r"))
        pid = msg.segment("PID")
        ident = (_f(pid, 3, 3) or "HL7", _f(pid, 3, 0) or _f(pid, 3))
        when_default = ""
        for seg in msg:
            kind = str(seg[0])
            if kind == "OBR":
                when_default = _f(seg, 7)
            if kind != "OBX":
                continue
            vtype, raw = _f(seg, 2), _f(seg, 5)
            value: Any = float(raw) if vtype in ("NM", "SN") else raw
            system = HL7_SYSTEMS.get(_f(seg, 3, 2), _f(seg, 3, 2))
            out.append(RawObservation(
                record_id=f"{_f(msg.segment('MSH'), 10)}-{_f(seg, 1)}",
                code=Code(system=system, code=_f(seg, 3, 0) or _f(seg, 3),
                          display=_f(seg, 3, 1) or None),
                value=value, unit=_f(seg, 6) or "1",
                effective_time=_hl7_time(_f(seg, 14) or when_default), source="import",
                identifier=ident if not is_hdt_id(ident[1]) else None,
                hdt_id=ident[1] if is_hdt_id(ident[1]) else None))
    return out


def from_csv(text: str) -> list[RawObservation]:
    """Columns: record_id, hdt_id or identifier_system + identifier_value, code_system,
    code, value, unit, effective_time, source (optional)."""
    out = []
    for row in csv.DictReader(io.StringIO(text)):
        value: Any = row["value"]
        with contextlib.suppress(ValueError):
            value = float(value)
        payload: dict[str, Any] = {
            "record_id": row.get("record_id") or None,
            "hdt_id": row.get("hdt_id") or None,
            "code": {"system": SYSTEMS.get(row["code_system"], row["code_system"]),
                     "code": row["code"]},
            "value": value, "unit": row.get("unit") or "1",
            "effective_time": _parse_time(row["effective_time"]).isoformat(),
            "source": row.get("source") or "import"}
        if row.get("identifier_value"):
            payload["identifier"] = {"system": row.get("identifier_system", "csv"),
                                     "value": row["identifier_value"]}
        out.append(raw_from_payload(payload))
    return out


@dataclass
class StoredObject:
    hdt_id: str
    key: str
    detail: dict[str, str]


class BatchImporter:
    def __init__(self, pipeline: IngestPipeline) -> None:
        self.pipeline = pipeline

    async def observations(self, fmt: str, body: bytes) -> IngestResult:
        if fmt == "fhir":
            import json

            raws = from_fhir_bundle(json.loads(body))
        elif fmt == "hl7v2":
            raws = from_hl7v2(body.decode("utf-8"))
        elif fmt == "csv":
            raws = from_csv(body.decode("utf-8"))
        else:
            raise ValueError(f"unknown observation format {fmt}")
        return await self.pipeline.process(raws)

    async def _subject(self, hdt_id: str | None, identifier: tuple[str, str] | None) -> str:
        if hdt_id:
            return hdt_id
        if identifier:
            return await self.pipeline.pseudonyms.hdt_id(*identifier)
        raise ValueError("the upload names no subject")

    async def dicom(self, body: bytes) -> StoredObject:
        ds = pydicom.dcmread(io.BytesIO(body))
        patient = str(ds.get("PatientID", ""))
        hdt_id = patient if is_hdt_id(patient) else await self._subject(
            None, ("DICOM", patient) if patient else None)
        ds.PatientID = hdt_id
        ds.PatientName = hdt_id
        for tag in ("PatientBirthDate", "PatientAddress", "OtherPatientIDs"):
            if tag in ds:
                delattr(ds, tag)
        buf = io.BytesIO()
        ds.save_as(buf)
        data = buf.getvalue()
        uids = await self.pipeline.backends.imaging.store(data)
        key = f"{IMAGING_BUCKET}/{uids['study_uid']}/{uids['sop_uid']}.dcm"
        await self.pipeline.backends.objects.put(key, data, content_type="application/dicom")
        return StoredObject(hdt_id, key, uids)

    async def vcf(self, body: bytes, *, hdt_id: str | None = None,
                  identifier: tuple[str, str] | None = None) -> StoredObject:
        subject = await self._subject(hdt_id, identifier)
        data = body if body[:2] == b"\x1f\x8b" else gzip.compress(body)
        text = gzip.decompress(data)[:1024]
        if not text.startswith(b"##fileformat=VCF"):
            raise ValueError("the upload is not a VCF file")
        digest = hashlib.sha256(data).hexdigest()[:16]
        key = f"{GENOMICS_BUCKET}/{subject}/{digest}.vcf.gz"
        await self.pipeline.backends.objects.put(key, data, content_type="application/gzip")
        return StoredObject(subject, key, {"sha256_prefix": digest})

