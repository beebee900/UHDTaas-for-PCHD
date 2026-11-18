"""OpenMRS client over the FHIR2 module (design 05, 5.3, OpenMRS RefApp 3 as the EMR).

Endpoints as documented on the OpenMRS wiki: base `/openmrs/ws/fhir2/R4`, the
CapabilityStatement at `/metadata`, `Patient` read and search (`identifier`, `name`,
`given`, `family`, `gender`, `birthdate`), `Observation` read and search (`patient`,
`subject`, `encounter`, `code`, `date`). Requests use HTTP Basic authentication, as the
OpenMRS REST API does.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import httpx

from apdt.integration.inbox import Filed, IntegrationInbox
from apdt.records.episodes import PATIENT_SYSTEM
from atra.ids import is_hdt_id

FHIR_JSON = "application/fhir+json"


class OpenMrsFhirClient:
    def __init__(self, base_url: str, username: str, password: str, *,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.http = httpx.AsyncClient(base_url=base_url.rstrip("/"), auth=(username, password),
                                      transport=transport, timeout=30,
                                      headers={"accept": FHIR_JSON})

    async def aclose(self) -> None:
        await self.http.aclose()

    async def _get(self, path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        resp = await self.http.get(path, params=dict(params or {}))
        resp.raise_for_status()
        return dict(resp.json())

    async def metadata(self) -> dict[str, Any]:
        return await self._get("/metadata")

    async def search(self, resource_type: str, **params: str) -> list[dict[str, Any]]:
        """All matches, following the Bundle's `next` links."""
        out: list[dict[str, Any]] = []
        page = await self._get(f"/{resource_type}", params)
        while True:
            out += [e["resource"] for e in page.get("entry", []) if "resource" in e]
            nxt = next((link["url"] for link in page.get("link", [])
                        if link.get("relation") == "next"), None)
            if nxt is None:
                return out
            resp = await self.http.get(nxt)
            resp.raise_for_status()
            page = dict(resp.json())

    async def read(self, resource_type: str, resource_id: str) -> dict[str, Any]:
        return await self._get(f"/{resource_type}/{resource_id}")

    async def patients_by_identifier(self, identifier: str) -> list[dict[str, Any]]:
        return await self.search("Patient", identifier=identifier)

    async def observations(self, patient_id: str, *, code: str | None = None,
                           date: str | None = None) -> list[dict[str, Any]]:
        params = {"patient": patient_id}
        if code:
            params["code"] = code
        if date:
            params["date"] = date
        return await self.search("Observation", **params)


def patient_index(client: OpenMrsFhirClient) -> Any:
    """A PatientIndex for the inbox: an OpenMRS identifier → the hdt_id recorded on the
    same OpenMRS patient (as another identifier), if there is one."""

    async def lookup(system: str, value: str) -> str | None:
        for patient in await client.patients_by_identifier(value):
            for ident in patient.get("identifier", []):
                if is_hdt_id(str(ident.get("value", ""))):
                    return str(ident["value"])
        return None

    return lookup


async def import_observations(client: OpenMrsFhirClient, inbox: IntegrationInbox,
                              tenant_id: str, patient_id: str, hdt_id: str, *,
                              code: str | None = None) -> Filed:
    """Copies a patient's OpenMRS observations into their active episode."""
    subject = {"identifier": {"system": PATIENT_SYSTEM, "value": hdt_id}}
    entries = []
    for obs in await client.observations(patient_id, code=code):
        body = {k: v for k, v in obs.items() if k not in ("meta", "encounter", "text")}
        body["subject"] = subject
        body["id"] = f"omrs-{obs['id']}"[:64]
        entries.append({"resource": body})
    return await inbox.accept(tenant_id, {"resourceType": "Bundle", "type": "collection",
                                          "identifier": {"value": f"openmrs:{patient_id}"},
                                          "entry": entries}, source="openmrs")
