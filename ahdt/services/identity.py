"""Re-identification from the identity table (design 04, 4.7.2).

`person_id` to `hdt_id` lives in the ingest identity table. Reading it back to a direct
identifier is an audited action open to the administrator with the purpose `operations`.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel
from sqlalchemy import select

from ahdt.stores import tables
from atra.contracts import Role
from atra.ids import is_hdt_id
from atra.service import Problem, authenticate, verifier_of


class ReidentifyRequest(BaseModel):
    hdt_id: str


def mount_identity(app: FastAPI) -> None:
    @app.post("/v1/identity/reidentify", tags=["identity"],
              summary="Direct identifiers recorded for an hdt_id (audited)")
    async def reidentify(body: ReidentifyRequest, request: Request) -> dict[str, Any]:
        ident = await authenticate(request.headers, await verifier_of(app), hdt_id=body.hdt_id)
        denied = (ident.ctx.actor_role is not Role.ADMINISTRATOR
                  or ident.ctx.purpose != "operations")
        app.state.audit.append(
            actor={"id": ident.ctx.actor_id, "role": ident.ctx.actor_role.value},
            action="identity.reidentify", target=body.hdt_id, purpose=ident.ctx.purpose,
            outcome="denied" if denied else "ok", hdt_id=body.hdt_id,
            tenant_id=ident.tenant_id)
        if denied:
            raise Problem(403, "forbidden",
                          "re-identification is for the administrator with purpose operations")
        if not is_hdt_id(body.hdt_id):
            raise Problem(422, "invalid-arguments", "not an hdt_id")
        pipe = await app.state.runtime.pipeline()
        async with pipe.backends.relational.engine().begin() as conn:
            rows = (await conn.execute(select(tables.identity).where(
                tables.identity.c.hdt_id == body.hdt_id))).all()
        return {"hdt_id": body.hdt_id,
                "identifiers": [{"system": r.system, "value": r.value} for r in rows]}
