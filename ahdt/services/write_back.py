"""Receiving end of the `ClinicalFindingWriteBackConnector` (design 04, 4.7.2).

    POST /v1/persons/{hdt_id}/findings

The body is the connector `Message` as the APDT sent it. A service client needs the SMART
scope `system/Condition.c`, and the person's consent must cover the message's purpose. The
finding is stored as a FHIR Condition in the `ahdt` partition, so `GET /v1/fhir/Condition`
returns it. A message that arrives twice is stored once.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from ahdt.knowledge.documents import PARTITION
from ahdt.services.fhir import SCOPE
from atra.connectors import Message
from atra.gateway import ClinicalFindingWriteBackConnector
from atra.security import InvalidToken, bearer
from atra.service import Problem, verifier_of

WRITE_BACK_TAG = "https://atra.health/fhir/CodeSystem/write-back"
CONTRACT = ClinicalFindingWriteBackConnector.OUT_CONTRACT


def smart_creates(scopes: frozenset[str], resource_type: str) -> bool:
    """A scope creates `resource_type` when its type matches and its permissions include
    create (`c` in SMART v2, `write` or `*` in SMART v1)."""
    for scope in scopes:
        m = SCOPE.match(scope)
        if m and m["type"] in ("*", resource_type) and (
                m["perm"] in ("write", "*") or "c" in m["perm"]):
            return True
    return False


def condition_of(msg: Message, hdt_id: str) -> dict[str, Any]:
    p = msg.payload
    return {
        "resourceType": "Condition", "id": f"wb-{msg.msg_id}",
        "meta": {"tag": [{"system": WRITE_BACK_TAG, "code": "apdt"}]},
        "clinicalStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-clinical",
            "code": "active"}]},
        "verificationStatus": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-ver-status",
            "code": p["status"]}]},
        "category": [{"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/condition-category",
            "code": "encounter-diagnosis"}]}],
        "code": {"coding": [{"system": p["system"], "code": p["code"],
                             "display": p["display"]}], "text": p["display"]},
        "subject": {"reference": f"Patient/{hdt_id}"},
        "recordedDate": p["recorded_at"],
        "recorder": {"display": p["author_role"]},
        **({"identifier": [{"system": "urn:atra:episode", "value": p["episode_id"]}]}
           if p.get("episode_id") else {})}


def mount_write_back(app: FastAPI) -> None:
    @app.post("/v1/persons/{hdt_id}/findings", tags=["coupling"], status_code=201,
              summary="Store a clinician-confirmed finding written back by the APDT")
    async def finding(hdt_id: str, request: Request) -> dict[str, Any]:
        try:
            claims = (await verifier_of(app)).verify(
                bearer(request.headers.get("authorization")))
        except InvalidToken as exc:
            raise Problem(401, "unauthenticated", str(exc)) from exc
        if not claims.is_service or not smart_creates(claims.scopes, "Condition"):
            raise Problem(403, "forbidden", "no SMART scope creates Condition")
        try:
            msg = Message.from_bytes(await request.body())
            CONTRACT.validate(msg.payload)
        except (TypeError, ValueError) as exc:
            raise Problem(422, "invalid-request", str(exc)) from exc
        if msg.content_hash() != msg.provenance.get("content_hash"):
            raise Problem(422, "invalid-request", "content hash mismatch")
        if not msg.target.startswith(f"hdt://{hdt_id}/"):
            raise Problem(422, "invalid-request", "the message names another person")
        if msg.payload["resource_type"] != "Condition":
            raise Problem(422, "invalid-request", "only Condition findings are stored")
        consent = app.state.consents.get(hdt_id)
        if consent is None or msg.purpose not in consent.purposes:
            raise Problem(403, "forbidden", f"no consent for {msg.purpose}")
        resource = condition_of(msg, hdt_id)
        pipe = await app.state.runtime.pipeline()
        try:
            await pipe.backends.fhir.create(resource, partition=PARTITION)
            created = True
        except FileExistsError:
            created = False
        app.state.audit.append(
            actor={"id": claims.client_id or claims.sub, "role": "service"},
            action="fhir.write_back", target=f"Condition/{resource['id']}",
            purpose=msg.purpose, outcome="ok", hdt_id=hdt_id)
        return {"resource": f"Condition/{resource['id']}", "created": created}
