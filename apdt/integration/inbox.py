"""Files mapped hospital-system resources into the right episode (design 05, 5.3).

Both integration paths end here: the p0 mapping (`hl7v2`, `dicom_sr`) and the Mirth
channels, which post a FHIR `collection` Bundle. For each Bundle the inbox:

1. finds the patient (`hdt_id`) from the subject identifier
2. finds the episode: the one holding the ServiceRequest named in `basedOn`, else the
   patient's latest active episode; an admission (`Encounter` in progress) opens one
3. puts lab values whose code belongs to an AHDT twin field into the field's UCUM unit
   (WP12 `harmonise`)
4. stores each resource in the episode, replacing an earlier version with the same id
5. pages critical results and writes one audit record per message
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ahdt.ingest.fields import FieldIndex, field_index
from ahdt.ingest.harmonise import HarmoniseError, RawObservation, harmonise
from apdt.integration.critical import CriticalPager
from apdt.integration.hl7v2 import PLACER_SYSTEM
from apdt.records.episodes import EPISODE_EXT, PATIENT_SYSTEM, EpisodeRecord
from atra.backends.base import FhirBackend
from atra.contracts import Code
from atra.provenance import AuditLog

type PatientIndex = Callable[[str, str], Awaitable[str | None]]
"""(identifier system, value) → hdt_id, for identifiers other than the hdt_id itself."""
INTEGRATION_ACTOR = {"id": "integration", "role": "system"}


class FilingError(LookupError):
    """A message that cannot be filed: unknown patient or no episode."""


@dataclass
class Filed:
    episode_id: str
    hdt_id: str
    resources: list[dict[str, Any]] = field(default_factory=list)
    alerts: list[dict[str, Any]] = field(default_factory=list)


async def _no_index(system: str, value: str) -> str | None:
    return None


class IntegrationInbox:
    def __init__(self, fhir: FhirBackend, audit: AuditLog, *,
                 patient_index: PatientIndex = _no_index, pager: CriticalPager | None = None,
                 fields: FieldIndex | None = None,
                 age_of: Callable[[str], float | None] = lambda _: None) -> None:
        self.fhir = fhir
        self.audit = audit
        self.patient_index = patient_index
        self.pager = pager
        self.fields = fields or field_index()
        self.age_of = age_of

    async def hdt_id_of(self, subject: Mapping[str, Any]) -> str:
        ident = subject.get("identifier") or {}
        system, value = str(ident.get("system", "")), str(ident.get("value", ""))
        if system == PATIENT_SYSTEM and value:
            return value
        hdt_id = await self.patient_index(system, value) if value else None
        if hdt_id is None:
            raise FilingError("the message names a patient this facility does not know")
        return hdt_id

    async def _episode(self, record: EpisodeRecord, hdt_id: str,
                       resources: list[dict[str, Any]]) -> str:
        placers = {b["identifier"]["value"] for r in resources for b in r.get("basedOn", [])
                   if b.get("identifier", {}).get("system") == PLACER_SYSTEM}
        if placers:
            for sr in await self.fhir.search("ServiceRequest", partition=record.tenant_id):
                if any(i.get("value") in placers for i in sr.get("identifier", [])):
                    for ext in sr.get("extension", []):
                        if ext.get("url") == EPISODE_EXT:
                            return str(ext["valueReference"]["reference"]).split("/")[-1]
        active = [e for e in await record.episodes_of(hdt_id) if e["status"] == "active"]
        if active:
            return str(max(active, key=lambda e: e["period"]["start"])["id"])
        admission = next((r for r in resources if r["resourceType"] == "Encounter"
                          and r["status"] == "in-progress"), None)
        if admission is not None:
            start = admission.get("period", {}).get("start")
            episode = await record.open(hdt_id, reason="Admission",
                                        at=datetime.fromisoformat(start) if start else None)
            return str(episode["id"])
        raise FilingError(f"no active episode for {hdt_id} at {record.tenant_id}")

    def _harmonise(self, obs: dict[str, Any]) -> dict[str, Any]:
        q = obs.get("valueQuantity")
        if not q or "value" not in q:
            return obs
        codings = obs["code"]["coding"]
        raw = RawObservation(
            record_id=obs["id"], code=Code(system=codings[0]["system"], code=codings[0]["code"]),
            alt_codes=[Code(system=c["system"], code=c["code"]) for c in codings[1:]],
            value=float(q["value"]), unit=str(q.get("code") or q.get("unit") or "1"),
            effective_time=datetime.fromisoformat(
                str(obs.get("effectiveDateTime", "1970-01-01T00:00:00+00:00"))))
        try:
            h = harmonise(raw, self.fields)
        except HarmoniseError:
            return obs
        out = dict(obs)
        out["valueQuantity"] = {**q, "value": h.value, "unit": h.unit, "code": h.unit}
        return out

    async def _store(self, record: EpisodeRecord, eid: str,
                     resource: dict[str, Any]) -> dict[str, Any]:
        body = {k: v for k, v in resource.items() if k not in ("subject", "meta")}
        try:
            return await record.add(eid, body)
        except FileExistsError:
            current = await self.fhir.read(body["resourceType"], body["id"],
                                           partition=record.tenant_id)
            merged = {**body, "subject": current.get("subject"),
                      "extension": current.get("extension", [])}
            if "episodeOfCare" in current:
                merged["episodeOfCare"] = current["episodeOfCare"]
            return await self.fhir.update(merged, partition=record.tenant_id)

    async def accept(self, tenant_id: str, bundle: Mapping[str, Any], *,
                     source: str, clinician: str | None = None) -> Filed:
        resources = [dict(e["resource"]) for e in bundle.get("entry", []) if "resource" in e]
        control = str(bundle.get("identifier", {}).get("value", ""))
        record = EpisodeRecord(self.fhir, tenant_id)
        try:
            if not resources:
                raise FilingError("the Bundle holds no resources")
            subject = next((r["subject"] for r in resources if "subject" in r), None)
            if subject is None:
                raise FilingError("no resource names a patient")
            hdt_id = await self.hdt_id_of(subject)
            eid = await self._episode(record, hdt_id, resources)
        except FilingError as exc:
            self.audit.append(actor=INTEGRATION_ACTOR, tenant_id=tenant_id, action="file",
                              target=f"{source}:{control}", purpose="care", outcome="error",
                              reason=str(exc))
            raise
        filed = Filed(episode_id=eid, hdt_id=hdt_id)
        responsible = clinician or await self._responsible(record, eid)
        for r in resources:
            if r["resourceType"] == "Observation":
                r = self._harmonise(r)
            stored = await self._store(record, eid, r)
            filed.resources.append(stored)
            if r["resourceType"] == "Observation" and self.pager is not None:
                filed.alerts += await self.pager.page(
                    stored, tenant_id=tenant_id, hdt_id=hdt_id, episode_id=eid,
                    clinician=responsible, age_years=self.age_of(hdt_id))
        self.audit.append(actor=INTEGRATION_ACTOR, tenant_id=tenant_id, hdt_id=hdt_id,
                          episode_id=eid, action="file", target=f"{source}:{control}",
                          purpose="care", outcome="ok")
        return filed

    async def _responsible(self, record: EpisodeRecord, eid: str) -> str:
        """The episode's care manager, else the tenant's on-duty medical officer."""
        manager = (await record.get(eid)).get("careManager", {}).get("identifier", {})
        return str(manager.get("value") or f"medical_officer.{record.tenant_id}")
