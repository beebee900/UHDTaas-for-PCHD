"""Write-back of confirmed diagnoses through the ClinicalFindingWriteBackConnector."""

from datetime import UTC, datetime

import httpx

from apdt.services.ahdt_access import AHDTAccess
from apdt.services.write_back import AHDTWriteBack
from atra import contracts as c
from atra.connectors import ConnectorState, Message
from atra.consent import ConsentRegistry
from atra.gateway import PatientConsent
from atra.provenance import AuditLog

HDT = "hdt-0123456789ab"
EP = c.Episode(episode_id="ep-2026-000001", tenant_id="fac-a", hdt_id=HDT, status="open",
               opened_at=datetime.now(UTC), reason="Fever",
               responsible_clinician="medical_officer.fac-a")
CODE = {"system": "http://snomed.info/sct", "code": "62676009", "display": "P. falciparum malaria"}


def rec(status="accepted", kind="diagnosis"):
    return c.Recommendation.model_validate({
        "recommendation_id": "rec-ep-2026-000001-1", "kind": kind, "hdt_id": HDT,
        "episode_id": EP.episode_id, "status": status, "confidence": 0.9,
        "payload": {"code": CODE, "name": CODE["display"]}, "bundle_id": None,
        "autonomy_level": "recommend", "created_by_agent": "differential-diagnosis-agent"})


def decided(role="medical_officer"):
    return c.ClinicalDecision(decision_id="d-1", recommendation_id="rec-ep-2026-000001-1",
                              decided_by={"id": f"{role}.fac-a", "role": role},
                              decision="accept", signature="sig")


def writer(handler, purposes=("care",)):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="http://ahdt")
    access = AHDTAccess("http://ahdt", lambda: "token", ConsentRegistry(), client)
    audit = AuditLog("apdt")
    consents = ConsentRegistry({HDT: PatientConsent(set(purposes))})
    return AHDTWriteBack(access, lambda: "token", consents, audit), audit


def outcomes(audit):
    return [(r.outcome, r.reason) for r in audit if r.action == "ahdt.write_back"]


async def test_a_finding_is_kept_while_the_ahdt_is_down_and_sent_later():
    up, got = False, []

    def ahdt(request):
        if not up:
            raise httpx.ConnectError("down", request=request)
        got.append(Message.from_bytes(request.content))
        assert request.url.path == f"/v1/persons/{HDT}/findings"
        return httpx.Response(201, json={"created": True})

    wb, audit = writer(ahdt)
    await wb.diagnosis(rec(), decided(), EP)
    assert wb.connectors[HDT].state is ConnectorState.DEGRADED
    up = True
    await wb.diagnosis(rec("signed"), decided(), EP)
    assert [m.payload["status"] for m in got] == ["provisional", "confirmed"]
    assert got[0].payload["code"] == "62676009" and got[0].payload["episode_id"] == EP.episode_id
    assert [o for o, _ in outcomes(audit)] == ["degraded", "ok"]
    assert wb.connectors[HDT].state is ConnectorState.RUNNING


async def test_only_confirmed_diagnoses_from_clinicians_with_consent_are_sent():
    sent = []

    def ahdt(request):
        sent.append(request)
        return httpx.Response(201, json={"created": True})

    wb, audit = writer(ahdt)
    await wb.diagnosis(rec("overridden"), decided(), EP)
    await wb.diagnosis(rec(kind="treatment"), decided(), EP)
    await wb.diagnosis(rec(), decided("patient"), EP)
    no_consent, audit2 = writer(ahdt, purposes=())
    await no_consent.diagnosis(rec(), decided(), EP)
    assert not sent
    assert [o for o, _ in outcomes(audit)] == ["denied"]
    assert outcomes(audit2)[0][0] == "denied" and "consent" in outcomes(audit2)[0][1]
