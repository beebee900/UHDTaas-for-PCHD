"""Read-only FHIR passthrough to the `ahdt` partition (design 04, 4.7.2).

    GET /v1/fhir/{type}/{id}
    GET /v1/fhir/{type}?patient={hdt_id}&code=...&date=ge...

A service client needs a SMART scope that reads the resource type (`system/Observation.rs`,
`system/*.rs`). A person reads their own record. Every other human role needs consent for
care. Searches are always limited to one person, and every call is audited.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from typing import Any

from fastapi import FastAPI, Request

from ahdt.knowledge.documents import PARTITION
from atra.contracts import Role
from atra.service import Identity, Problem, authenticate, verifier_of

RESOURCE_TYPES = frozenset({
    "Patient", "Observation", "Condition", "MedicationStatement", "DocumentReference",
    "DiagnosticReport", "Consent"})
SEARCH_PARAMS = frozenset({"code", "status", "category", "date", "encounter", "_tag", "_id"})
READ_ROLES = frozenset({Role.MEDICAL_OFFICER, Role.NURSE, Role.PHARMACIST,
                        Role.LAB_SCIENTIST, Role.RADIOLOGIST})
SCOPE = re.compile(r"^(?:system|user|patient)/(?P<type>\*|[A-Za-z]+)\.(?P<perm>[A-Za-z*]+)$")


def smart_allows(scopes: Iterable[str], resource_type: str) -> bool:
    """A scope reads `resource_type` when its type matches and its permissions include read
    (`r` or `s` in SMART v2, `read` or `*` in SMART v1)."""
    for scope in scopes:
        m = SCOPE.match(scope)
        if m and m["type"] in ("*", resource_type):
            perm = m["perm"]
            if perm in ("read", "*") or (set(perm) & {"r", "s"} and set(perm) <= set("cruds")):
                return True
    return False


def mount_fhir(app: FastAPI) -> None:
    async def caller(request: Request, resource_type: str, hdt_id: str | None) -> Identity:
        if resource_type not in RESOURCE_TYPES:
            raise Problem(404, "not-found", f"{resource_type} is not served")
        ident = await authenticate(request.headers, await verifier_of(app), hdt_id=hdt_id)
        if ident.claims.is_service and not smart_allows(ident.claims.scopes, resource_type):
            raise Problem(403, "forbidden", f"no SMART scope reads {resource_type}")
        own = ident.claims.hdt_id == hdt_id and not ident.delegated
        if not own and ident.ctx.actor_role not in READ_ROLES:
            raise Problem(403, "forbidden", "this role may not read records")
        consent = app.state.consents.get(hdt_id or "")
        if not own and (consent is None or ident.ctx.purpose not in consent.purposes):
            raise Problem(403, "forbidden", f"no consent for {ident.ctx.purpose}")
        return ident

    def audit(ident: Identity, target: str, hdt_id: str | None) -> None:
        app.state.audit.append(
            actor={"id": ident.ctx.actor_id, "role": ident.ctx.actor_role.value},
            action="fhir.read", target=target, purpose=ident.ctx.purpose, outcome="ok",
            hdt_id=hdt_id, tenant_id=ident.tenant_id)

    @app.get("/v1/fhir/{resource_type}/{resource_id}", tags=["fhir"],
             summary="Read one FHIR resource of a person")
    async def read(resource_type: str, resource_id: str, request: Request) -> dict[str, Any]:
        runtime = app.state.runtime
        pipe = await runtime.pipeline()
        try:
            resource = await pipe.backends.fhir.read(resource_type, resource_id,
                                                     partition=PARTITION)
        except (KeyError, LookupError):
            raise Problem(404, "not-found", f"no {resource_type}/{resource_id}") from None
        subject = _subject(resource)
        ident = await caller(request, resource_type, subject)
        audit(ident, f"{resource_type}/{resource_id}", subject)
        return dict(resource)

    @app.get("/v1/fhir/{resource_type}", tags=["fhir"],
             summary="Search the FHIR resources of one person")
    async def search(resource_type: str, request: Request) -> dict[str, Any]:
        params = dict(request.query_params)
        ref = params.pop("patient", None) or params.pop("subject", None)
        if ref is None:
            raise Problem(400, "bad-request", "a search names its patient")
        hdt_id = ref.removeprefix("Patient/")
        unknown = set(params) - SEARCH_PARAMS
        if unknown:
            raise Problem(400, "bad-request",
                          f"unsupported search parameters: {', '.join(sorted(unknown))}")
        ident = await caller(request, resource_type, hdt_id)
        pipe = await app.state.runtime.pipeline()
        found = await pipe.backends.fhir.search(
            resource_type, {"subject": f"Patient/{hdt_id}", **params}, partition=PARTITION)
        audit(ident, f"{resource_type}?patient={hdt_id}", hdt_id)
        return {"resourceType": "Bundle", "type": "searchset", "total": len(found),
                "entry": [{"resource": r} for r in found]}


def _subject(resource: dict[str, Any]) -> str | None:
    if resource.get("resourceType") == "Patient":
        return str(resource.get("id"))
    ref = (resource.get("subject") or resource.get("patient") or {}).get("reference", "")
    return str(ref).removeprefix("Patient/") or None
