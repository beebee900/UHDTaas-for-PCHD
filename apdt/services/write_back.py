"""Write-back of clinician-confirmed diagnoses to the AHDT Whole-Body DT (design 05, 5.7).

A diagnosis that the medical officer accepts, edits or signs is published through the
supplied `ClinicalFindingWriteBackConnector`, which refuses unsigned and agent-authored
findings. Its transport posts each message to the AHDT (`POST /v1/persons/{hdt_id}/findings`),
which stores it as a FHIR Condition. When the AHDT cannot be reached the connector keeps the
message and sends it before the next write-back.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from apdt.services.ahdt_access import AHDTAccess
from atra import contracts as c
from atra.connectors import (
    ConnectorState,
    ConsentPolicy,
    DTKind,
    Handler,
    PolicyDenied,
    QoS,
    Transport,
    TwinEndpoint,
)
from atra.consent import ConsentRegistry
from atra.gateway import ClinicalFindingWriteBackConnector
from atra.provenance import AuditLog

WRITE_BACK_STATUSES = frozenset({"accepted", "edited", "signed"})
SCOPE = "system/Condition.c"
QOS = QoS(max_retries=1, backoff_s=0.2)
type Outcome = Literal["ok", "denied", "degraded"]


class AHDTRefusedFinding(Exception):
    """The AHDT answered and refused the finding; sending it again would not help."""


class AHDTFindingTransport(Transport):
    """Posts each outbound connector message to the AHDT person it names."""

    def __init__(self, access: AHDTAccess, token: Callable[[], str]) -> None:
        self.access = access
        self.token = token
        self.refused: AHDTRefusedFinding | None = None

    async def connect(self) -> None:
        return None

    async def publish(self, topic: str, data: bytes) -> None:
        hdt_id = topic.split("/")[1]
        resp = await self.access.http().post(
            f"{self.access.ahdt_url}/v1/persons/{hdt_id}/findings", content=data,
            headers={"authorization": f"Bearer {self.token()}",
                     "content-type": "application/json"})
        if resp.status_code >= 500:
            raise ConnectionError(f"AHDT error {resp.status_code}")
        if resp.status_code >= 400:
            self.refused = AHDTRefusedFinding(f"HTTP {resp.status_code}: {resp.text[:200]}")

    async def subscribe(self, topic: str, handler: Handler) -> None:
        return None

    async def close(self) -> None:
        return None


class AHDTWriteBack:
    def __init__(self, access: AHDTAccess, token: Callable[[], str], consents: ConsentRegistry,
                 audit: AuditLog) -> None:
        self.transport = AHDTFindingTransport(access, token)
        self.consents = consents
        self.audit = audit
        self.connectors: dict[str, ClinicalFindingWriteBackConnector] = {}
        self._lock = asyncio.Lock()

    async def connector(self, hdt_id: str) -> ClinicalFindingWriteBackConnector:
        found = self.connectors.get(hdt_id)
        if found is None:
            found = ClinicalFindingWriteBackConnector(
                TwinEndpoint(hdt_id, DTKind.PATIENT), TwinEndpoint(hdt_id, DTKind.WHOLE_BODY),
                self.transport, qos=QOS)
            await found.start()
            self.connectors[hdt_id] = found
        consent = self.consents.get(hdt_id)
        found.policies = [ConsentPolicy({(DTKind.PATIENT, DTKind.WHOLE_BODY):
                                         set(consent.purposes) if consent else set()})]
        return found

    async def diagnosis(self, rec: c.Recommendation, decision: c.ClinicalDecision,
                        ep: c.Episode) -> None:
        """Writes `rec` back when it is a diagnosis that a clinician has confirmed."""
        if rec.kind != "diagnosis" or rec.status not in WRITE_BACK_STATUSES:
            return
        code = rec.payload.get("code")
        if not code:
            self._audit(ep, rec, "degraded", "the diagnosis has no SNOMED CT code")
            return
        finding: dict[str, Any] = {
            "resourceType": "Condition",
            "status": "confirmed" if rec.status == "signed" else "provisional",
            "signed_by": decision.decided_by.id, "author_role": decision.decided_by.role.value,
            "recorded_at": (decision.signed_at or datetime.now(UTC)).isoformat(),
            "episode_id": ep.episode_id,
            "code": {"coding": [{"system": code["system"], "code": code["code"],
                                 "display": code.get("display") or rec.payload.get("name")}]}}
        async with self._lock:
            connector = await self.connector(ep.hdt_id)
            self.transport.refused = None
            try:
                await connector.flush()
                await connector.publish(finding)
            except (PolicyDenied, ValueError) as exc:
                self._audit(ep, rec, "denied", str(exc))
                return
            if self.transport.refused is not None:
                self._audit(ep, rec, "denied", str(self.transport.refused))
            elif connector.state is ConnectorState.DEGRADED:
                self._audit(ep, rec, "degraded", "AHDT unreachable; the finding is kept "
                                                 "and sent with the next write-back")
            else:
                self._audit(ep, rec, "ok", None)

    def _audit(self, ep: c.Episode, rec: c.Recommendation, outcome: Outcome,
               reason: str | None) -> None:
        self.audit.append(actor={"id": "apdt", "role": "system"}, tenant_id=ep.tenant_id,
                          hdt_id=ep.hdt_id, episode_id=ep.episode_id, action="ahdt.write_back",
                          target=rec.recommendation_id, purpose="care", outcome=outcome,
                          reason=reason)
