"""Health information exchange between facilities through OpenHIM (design 05, 5.3):
the referral bundle builder, sending through the OpenHIM router, and receipt at the target
facility.

A referral is a FHIR `collection` Bundle: a ServiceRequest (SNOMED CT 3457005 Patient
referral) from the sending facility to the receiving one, followed by the clinical
resources of the episode it names in `supportingInfo`. Resources travel without the
sender's episode link; the receiver files them in its own episode.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import Any

from fhir.resources.R4B.servicerequest import ServiceRequest

from apdt.integration.hl7v2 import PLACER_SYSTEM
from apdt.integration.inbox import Filed, FilingError, IntegrationInbox
from apdt.integration.openhim import OpenHimClient
from apdt.records.episodes import EPISODE_EXT, PATIENT_SYSTEM, EpisodeRecord
from atra.ids import uuid7

REFERRAL = {"system": "http://snomed.info/sct", "code": "3457005", "display": "Patient referral"}
REFERRAL_SYSTEM = "urn:atra:referral"
SHARED_TYPES = ("Condition", "Observation", "DiagnosticReport", "MedicationRequest",
                "MedicationDispense", "CarePlan", "Composition")


def _portable(resource: Mapping[str, Any], hdt_id: str) -> dict[str, Any]:
    out = {k: v for k, v in resource.items() if k not in ("meta", "episodeOfCare")}
    out["extension"] = [e for e in resource.get("extension", []) if e.get("url") != EPISODE_EXT]
    if not out["extension"]:
        del out["extension"]
    if "subject" in out:
        out["subject"] = {"identifier": {"system": PATIENT_SYSTEM, "value": hdt_id}}
    return out


PRIORITY = {"routine": "routine", "urgent": "urgent", "emergency": "stat"}


def build_referral(hdt_id: str, resources: Sequence[Mapping[str, Any]], *, from_tenant: str,
                   to_tenant: str, reason: str, requester: str, urgency: str = "routine",
                   types: Sequence[str] = SHARED_TYPES) -> dict[str, Any]:
    """The referral Bundle for one person from the episode's resources of `types`."""
    referral_id = f"ref-{uuid7()}"
    shared = [_portable(r, hdt_id) for t in types for r in resources
              if r.get("resourceType") == t]
    request = ServiceRequest.model_validate({
        "resourceType": "ServiceRequest", "id": referral_id, "status": "active",
        "intent": "order", "priority": PRIORITY[urgency],
        "identifier": [{"system": PLACER_SYSTEM, "value": referral_id}],
        "category": [{"coding": [REFERRAL]}], "code": {"coding": [REFERRAL]},
        "subject": {"identifier": {"system": PATIENT_SYSTEM, "value": hdt_id}},
        "authoredOn": datetime.now(UTC).isoformat(),
        "requester": {"identifier": {"value": requester}, "display": from_tenant},
        "performer": [{"identifier": {"value": to_tenant}}],
        "reasonCode": [{"text": reason}],
        "supportingInfo": [{"reference": f"{r['resourceType']}/{r['id']}"} for r in shared],
    }).model_dump(mode="json", exclude_none=True)
    return {"resourceType": "Bundle", "type": "collection",
            "identifier": {"system": REFERRAL_SYSTEM, "value": referral_id},
            "timestamp": datetime.now(UTC).isoformat(),
            "entry": [{"resource": request}, *({"resource": r} for r in shared)]}


async def referral_bundle(record: EpisodeRecord, episode_id: str, *, to_tenant: str,
                          reason: str, requester: str,
                          types: Sequence[str] = SHARED_TYPES) -> dict[str, Any]:
    episode = await record.get(episode_id)
    hdt_id = str(episode["patient"]["identifier"]["value"])
    resources = [r for t in types for r in await record.resources(episode_id, t)]
    return build_referral(hdt_id, resources, from_tenant=record.tenant_id,
                          to_tenant=to_tenant, reason=reason, requester=requester, types=types)


class HieRouter:
    """Sends referral bundles to another facility through the OpenHIM channel of that
    facility (`/referral/{tenant}`)."""

    def __init__(self, openhim: OpenHimClient) -> None:
        self.openhim = openhim

    async def send(self, to_tenant: str, bundle: Mapping[str, Any]) -> dict[str, Any]:
        resp = await self.openhim.send(f"/referral/{to_tenant}", bundle)
        return dict(resp.json())


async def receive_referral(inbox: IntegrationInbox, tenant_id: str, bundle: Mapping[str, Any],
                           *, source: str) -> Filed:
    """Opens an episode at the receiving facility when the patient has none, then files the
    referral and its resources there."""
    resources = [e["resource"] for e in bundle.get("entry", [])]
    request = next((r for r in resources if r["resourceType"] == "ServiceRequest"), None)
    if request is None:
        raise FilingError("a referral Bundle needs its ServiceRequest")
    hdt_id = await inbox.hdt_id_of(request["subject"])
    record = EpisodeRecord(inbox.fhir, tenant_id)
    if not any(e["status"] == "active" for e in await record.episodes_of(hdt_id)):
        reason = (request.get("reasonCode") or [{}])[0].get("text") or "Referral"
        await record.open(hdt_id, reason=f"Referral: {reason}")
    return await inbox.accept(tenant_id, {**bundle, "entry": [
        {"resource": {k: v for k, v in r.items() if k != "basedOn"}} for r in resources]},
        source=source)
