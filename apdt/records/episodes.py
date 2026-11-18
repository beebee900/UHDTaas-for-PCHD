"""Episode-of-care record: one FHIR partition per tenant, `EpisodeOfCare` as the root.

Every clinical resource of an episode carries an `EpisodeOfCare` reference in
`extension[episode]` (Encounter uses `episodeOfCare`), so the whole episode is one search.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from atra.backends.base import FhirBackend
from atra.ids import episode_id, new_record_id

EPISODE_EXT = "https://atra.health/fhir/StructureDefinition/episode"
PATIENT_SYSTEM = "https://atra.health/hdt-id"
# Resource types an episode holds (design 05, 5.4.1).
EPISODE_TYPES = ("Encounter", "Condition", "ServiceRequest", "Observation", "DiagnosticReport",
                 "MedicationRequest", "MedicationDispense", "MedicationAdministration",
                 "Procedure", "CarePlan", "Task", "Composition",
                 "QuestionnaireResponse")


class EpisodeRecord:
    def __init__(self, fhir: FhirBackend, tenant_id: str) -> None:
        self.fhir = fhir
        self.tenant_id = tenant_id
        self._counter = itertools.count(1)
        self._lock = threading.Lock()

    def _patient(self, hdt_id: str) -> dict[str, Any]:
        return {"identifier": {"system": PATIENT_SYSTEM, "value": hdt_id}}

    async def _next_episode_id(self, year: int) -> str:
        existing = await self.fhir.search("EpisodeOfCare", partition=self.tenant_id)
        used = {e["id"] for e in existing}
        with self._lock:
            while True:
                eid = episode_id(year, next(self._counter))
                if eid not in used:
                    return eid

    async def open(self, hdt_id: str, *, reason: str | None = None,
                   at: datetime | None = None) -> dict[str, Any]:
        at = at or datetime.now(UTC)
        eid = await self._next_episode_id(at.year)
        body: dict[str, Any] = {
            "resourceType": "EpisodeOfCare", "id": eid, "status": "active",
            "patient": self._patient(hdt_id),
            "managingOrganization": {"identifier": {"value": self.tenant_id}},
            "period": {"start": at.isoformat()}}
        if reason:
            body["type"] = [{"text": reason}]
        return await self.fhir.create(body, partition=self.tenant_id)

    async def get(self, eid: str) -> dict[str, Any]:
        return await self.fhir.read("EpisodeOfCare", eid, partition=self.tenant_id)

    async def close(self, eid: str, *, at: datetime | None = None) -> dict[str, Any]:
        episode = dict(await self.get(eid))
        episode["status"] = "finished"
        episode["period"] = {**episode.get("period", {}),
                             "end": (at or datetime.now(UTC)).isoformat()}
        return await self.fhir.update(episode, partition=self.tenant_id)

    async def add(self, eid: str, resource: Mapping[str, Any]) -> dict[str, Any]:
        rtype = resource["resourceType"]
        if rtype not in EPISODE_TYPES:
            raise ValueError(f"{rtype} is not an episode resource")
        episode = await self.get(eid)
        if episode["status"] != "active":
            raise ValueError(f"episode {eid} is {episode['status']}")
        body = {"id": new_record_id(), **resource}
        body.setdefault("subject", episode["patient"])
        ref = {"reference": f"EpisodeOfCare/{eid}"}
        if rtype == "Encounter":
            body["episodeOfCare"] = [ref]
        body["extension"] = [e for e in body.get("extension", []) if e.get("url") != EPISODE_EXT]
        body["extension"].append({"url": EPISODE_EXT, "valueReference": ref})
        return await self.fhir.create(body, partition=self.tenant_id)

    async def resources(self, eid: str, resource_type: str | None = None) -> list[dict[str, Any]]:
        out = []
        for rtype in (resource_type,) if resource_type else EPISODE_TYPES:
            for r in await self.fhir.search(rtype, partition=self.tenant_id):
                if any(e.get("url") == EPISODE_EXT
                       and e["valueReference"]["reference"] == f"EpisodeOfCare/{eid}"
                       for e in r.get("extension", [])):
                    out.append(r)
        return out

    async def episodes_of(self, hdt_id: str) -> list[dict[str, Any]]:
        return [e for e in await self.fhir.search("EpisodeOfCare", partition=self.tenant_id)
                if e["patient"]["identifier"]["value"] == hdt_id]
