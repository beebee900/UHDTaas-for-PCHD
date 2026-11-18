"""APDT integration routes (design 05, 5.3), for service clients only (Mirth, OpenHIM,
the ODK pull worker):

- `POST /v1/t/{tenant}/integration/hl7v2`: an HL7 v2 message or batch (p0 path)
- `POST /v1/t/{tenant}/integration/fhir`: a FHIR collection Bundle (Mirth path)
- `POST /v1/t/{tenant}/integration/dicom-sr`: a DICOM SR, raw or base64 (both paths)
- `POST /v1/t/{tenant}/integration/referral`: a referral Bundle from another facility
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, FastAPI, Request
from fhir.resources.R4B import get_fhir_model_class

from apdt.integration import dicom_sr, hie, hl7v2
from apdt.integration.inbox import Filed, FilingError, IntegrationInbox
from atra.security import InvalidToken, bearer
from atra.service import Problem, verifier_of


def _validate(bundle: Any) -> dict[str, Any]:
    if not isinstance(bundle, dict) or bundle.get("resourceType") != "Bundle":
        raise Problem(422, "invalid-request", "the body must be a FHIR Bundle")
    entries = []
    for e in bundle.get("entry", []):
        r = e.get("resource") or {}
        try:
            model = get_fhir_model_class(str(r.get("resourceType")))
            entries.append({"resource": dict(model.model_validate(r).model_dump(
                mode="json", exclude_none=True))})
        except (KeyError, ValueError) as exc:
            raise Problem(422, "invalid-request", f"invalid resource: {exc}") from exc
    return {**bundle, "entry": entries}


def _result(filed: Filed) -> dict[str, Any]:
    return {"episode_id": filed.episode_id, "hdt_id": filed.hdt_id,
            "resources": [f"{r['resourceType']}/{r['id']}" for r in filed.resources],
            "alerts": [a["alert_id"] for a in filed.alerts]}


def mount_integration(app: FastAPI, inbox: IntegrationInbox) -> None:
    app.state.integration = inbox
    r = APIRouter(prefix="/v1/t/{tenant_id}/integration", tags=["integration"])

    async def service(request: Request) -> str:
        try:
            claims = (await verifier_of(app)).verify(bearer(request.headers.get("authorization")))
        except InvalidToken as exc:
            raise Problem(401, "unauthenticated", str(exc)) from exc
        if not claims.is_service:
            raise Problem(403, "forbidden", "integration routes take service clients only")
        return claims.sub

    async def file(tenant_id: str, bundle: dict[str, Any], source: str) -> dict[str, Any]:
        try:
            return _result(await inbox.accept(tenant_id, bundle, source=source))
        except FilingError as exc:
            raise Problem(409, "not-filed", str(exc)) from exc

    @r.post("/hl7v2")
    async def from_hl7v2(request: Request, tenant_id: str) -> dict[str, Any]:
        client = await service(request)
        text = (await request.body()).decode("utf-8")
        out = []
        for message in hl7v2.split_batch(text):
            try:
                mapped = hl7v2.map_message(message)
            except (hl7v2.HL7MappingError, ValueError) as exc:
                raise Problem(422, "invalid-request", str(exc)) from exc
            out.append(await file(tenant_id, hl7v2.to_bundle(mapped), f"hl7v2:{client}"))
        return {"filed": out}

    @r.post("/fhir")
    async def from_fhir(request: Request, tenant_id: str) -> dict[str, Any]:
        client = await service(request)
        return await file(tenant_id, _validate(await request.json()), f"fhir:{client}")

    @r.post("/dicom-sr")
    async def from_dicom_sr(request: Request, tenant_id: str) -> dict[str, Any]:
        client = await service(request)
        try:
            mapped = dicom_sr.map_sr(await request.body())
        except Exception as exc:
            raise Problem(422, "invalid-request", f"not a readable DICOM SR: {exc}") from exc
        return await file(tenant_id, hl7v2.to_bundle(mapped), f"dicom-sr:{client}")

    @r.post("/referral")
    async def referral(request: Request, tenant_id: str) -> dict[str, Any]:
        client = await service(request)
        bundle = _validate(await request.json())
        try:
            received = await hie.receive_referral(inbox, tenant_id, bundle,
                                                  source=f"referral:{client}")
        except FilingError as exc:
            raise Problem(409, "not-filed", str(exc)) from exc
        return _result(received)

    app.include_router(r)
