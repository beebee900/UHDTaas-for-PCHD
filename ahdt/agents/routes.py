"""Route that runs a twin orchestrator or the conductor for one person and returns the report."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime
from typing import Annotated, Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from ahdt.agents.hub import AgentHub
from atra.connectors import DTKind
from atra.contracts import Role
from atra.service import Problem, authenticate, verifier_of

RUN_ROLES = frozenset({Role.MEDICAL_OFFICER, Role.NURSE, Role.PATIENT})


class PlanIn(BaseModel):
    plan_id: str
    twin: DTKind
    action: str
    risk: float = Field(0.0, ge=0, le=1)
    risk_to: dict[str, float] = Field(default_factory=dict)


class AgentRunRequest(BaseModel):
    """Name a `twin` to run its orchestrator, or a `person_goal` to run the conductor."""

    hdt_id: Annotated[str, Field(pattern=r"^hdt-[0-9a-f]{12}$")]
    twin: DTKind | None = None
    person_goal: str | None = None
    now: datetime | None = None
    triggers: list[str] = Field(default_factory=list)
    plans: list[PlanIn] = Field(default_factory=list)
    probes: list[str] = Field(default_factory=list,
                              description="Action classes to attempt, to show the guard's answer")


def mount_agents(app: FastAPI, hub: AgentHub) -> None:
    @app.post("/v1/agents/run", tags=["agents"],
              summary="Run a twin orchestrator or the conductor and return its report")
    async def run(body: AgentRunRequest, request: Request) -> dict[str, Any]:
        ident = await authenticate(request.headers, await verifier_of(app), hdt_id=body.hdt_id)
        role = ident.ctx.actor_role
        if role not in RUN_ROLES or (role is Role.PATIENT and ident.claims.hdt_id != body.hdt_id):
            raise Problem(403, "forbidden", "this role may not run agents for this person")
        if (body.twin is None) == (body.person_goal is None):
            raise Problem(422, "invalid-arguments", "give either twin or person_goal")
        ctx = replace(ident.ctx, hdt_id=body.hdt_id)
        if body.twin is not None:
            orchestrator = hub.orchestrator(body.twin)
            if orchestrator is None:
                raise Problem(404, "not-found", f"{body.twin.value} has no standing goals")
            out = await orchestrator.run(replace(ctx, agent=orchestrator.name), now=body.now,
                                         triggers=body.triggers, probes=body.probes)
            hub.reports[(body.hdt_id, body.twin.value)] = out.report
            return {"kind": "orchestrator", "status": out.result.status, **out.report}
        assert body.person_goal is not None
        report = await hub.conductor.submit_goal(
            body.person_goal, replace(ctx, agent=hub.conductor.name), now=body.now,
            plans=[p.model_dump(mode="json") for p in body.plans], probes=body.probes)
        return {"kind": "conductor", **report}
