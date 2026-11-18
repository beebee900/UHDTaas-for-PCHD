"""Consent: the FHIR Consent profile and its mapping to `PatientConsent` (design 03, 3.13)."""

from __future__ import annotations

import threading
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from atra.codes import SYSTEMS
from atra.contracts import CONSENT_CATEGORIES, PURPOSE_HL7, PurposeOfUse
from atra.gateway import PatientConsent

PROFILE = "https://atra.local/fhir/StructureDefinition/atra-consent"
TOOL_SYSTEM = "https://atra.local/fhir/CodeSystem/ahdt-tool"
_HL7_PURPOSE = {code: p for p, code in PURPOSE_HL7.items()}


def to_fhir(hdt_id: str, purposes: Iterable[PurposeOfUse | str],
            refused_tools: Iterable[str] = (), *, consent_id: str | None = None,
            actors: Iterable[Mapping[str, str]] = ()) -> dict[str, Any]:
    """FHIR R4 Consent: permit the purposes, with nested deny provisions for withheld tools."""
    permitted = [PurposeOfUse(p) for p in purposes]
    deny = [{"type": "deny", "code": [{"coding": [{"system": TOOL_SYSTEM, "code": t}]}]}
            for t in sorted(set(refused_tools))]
    provision: dict[str, Any] = {
        "type": "permit",
        "purpose": [{"system": SYSTEMS["purpose"], "code": PURPOSE_HL7[p]} for p in permitted],
        "provision": deny,
    }
    actor_list = list(actors)
    if actor_list:
        provision["actor"] = [{"role": {"text": a["role"]},
                               "reference": {"reference": a["reference"]}} for a in actor_list]
    body: dict[str, Any] = {
        "resourceType": "Consent",
        "meta": {"profile": [PROFILE]},
        "status": "active",
        "scope": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/consentscope",
                              "code": "patient-privacy"}]},
        "category": [{"coding": [{"system": "http://loinc.org", "code": "59284-0"}]}],
        "patient": {"reference": f"Patient/{hdt_id}"},
        "dateTime": datetime.now(UTC).isoformat(),
        "policyRule": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/v3-ActCode",
                                   "code": "OPTIN"}]},
        "provision": provision,
    }
    if consent_id:
        body["id"] = consent_id
    return body


def from_fhir(resource: Mapping[str, Any]) -> PatientConsent:
    """Map an active Consent to the gateway's `PatientConsent`; inactive grants nothing."""
    if resource.get("status") != "active":
        return PatientConsent(set(), set())
    provision = resource.get("provision", {})
    purposes = {_HL7_PURPOSE[c["code"]].value for c in provision.get("purpose", [])
                if c.get("code") in _HL7_PURPOSE}
    refused = {coding["code"] for sub in provision.get("provision", [])
               if sub.get("type") == "deny"
               for concept in sub.get("code", []) for coding in concept.get("coding", [])
               if coding.get("system") == TOOL_SYSTEM}
    return PatientConsent(purposes, refused)


def tools_for_categories(categories: Iterable[str]) -> set[str]:
    """Tools withheld by the consent categories a patient switched off in an app."""
    return {t for cat in categories for t in CONSENT_CATEGORIES[cat]}


class ConsentRegistry:
    """Current consent per `hdt_id`, kept in memory by each service."""

    def __init__(self, initial: Mapping[str, PatientConsent] | None = None) -> None:
        self._lock = threading.Lock()
        self._consents: dict[str, PatientConsent] = dict(initial or {})

    def get(self, hdt_id: str) -> PatientConsent | None:
        with self._lock:
            return self._consents.get(hdt_id)

    def set(self, hdt_id: str, consent: PatientConsent) -> None:
        with self._lock:
            self._consents[hdt_id] = consent

    def apply_fhir(self, resource: Mapping[str, Any]) -> PatientConsent:
        hdt_id = str(resource["patient"]["reference"]).split("/")[-1]
        consent = from_fhir(resource)
        self.set(hdt_id, consent)
        return consent

    def as_mapping(self) -> dict[str, PatientConsent]:
        with self._lock:
            return dict(self._consents)

    @staticmethod
    def policy_view(consent: PatientConsent | None) -> dict[str, Any] | None:
        if consent is None:
            return None
        return {"purposes": sorted(consent.purposes),
                "refused_tools": sorted(consent.refused_tools)}


def demo_registry() -> ConsentRegistry:
    """Consents of the demo personas: care, self-management and public health."""
    from atra.personas import PERSONAS

    purposes = {"care", "self_management", "public_health"}
    return ConsentRegistry({p.hdt_id: PatientConsent(set(purposes), set(p.withheld_tools))
                            for p in PERSONAS})
