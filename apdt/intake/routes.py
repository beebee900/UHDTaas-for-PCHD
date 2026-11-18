"""Questionnaire routes of the APDT API (design 05, 5.2.1), under `/v1/t/{tenant_id}`:

- `GET /questionnaires/{qid}`: the served Questionnaire and its renderer data
- `POST /questionnaires/{qid}/populate`: `{hdt_id}` → pre-filled QuestionnaireResponse
- `POST /questionnaires/{qid}/extract`: a completed QuestionnaireResponse → Observations;
  with `?episode_id=` both are filed in the episode
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Body, FastAPI, Request
from pydantic import BaseModel

from apdt.intake import questionnaires as qs
from apdt.records.episodes import PATIENT_SYSTEM, EpisodeRecord
from atra.backends import Backends
from atra.service import Problem

type Check = Callable[..., Awaitable[Any]]


class PopulateRequest(BaseModel):
    hdt_id: str


def mount_intake(app: FastAPI, check: Check) -> None:
    backends: Backends = app.state.backends
    kb_dir = app.state.settings.kb_dir
    r = APIRouter(prefix="/v1/t/{tenant_id}/questionnaires", tags=["questionnaires"])

    def served(qid: str) -> dict[str, Any]:
        try:
            return qs.served(qs.load(qid, kb_dir))
        except KeyError:
            raise Problem(404, "not-found", f"no questionnaire {qid}") from None

    @r.get("/{qid}")
    async def get_questionnaire(request: Request, tenant_id: str, qid: str) -> dict[str, Any]:
        await check(request, "questionnaires.read", tenant_id)
        q = served(qid)
        return {"questionnaire": q, "render": qs.render(q)}

    @r.post("/{qid}/populate")
    async def populate(request: Request, tenant_id: str, qid: str,
                       body: PopulateRequest) -> dict[str, Any]:
        await check(request, "questionnaires.populate", tenant_id, body.hdt_id)
        subject = {"identifier": {"system": PATIENT_SYSTEM, "value": body.hdt_id}}
        observations = [o for o in await backends.fhir.search("Observation", partition=tenant_id)
                        if o.get("subject") == subject]
        return qs.populate(served(qid), subject, observations, now=datetime.now(UTC))

    @r.post("/{qid}/extract")
    async def extract(request: Request, tenant_id: str, qid: str,
                      response: Annotated[dict[str, Any], Body()],
                      episode_id: str | None = None) -> dict[str, Any]:
        hdt_id = str(response.get("subject", {}).get("identifier", {}).get("value", ""))
        await check(request, "questionnaires.extract", tenant_id, hdt_id or None)
        try:
            observations = qs.extract(served(qid), response)
        except ValueError as exc:
            raise Problem(422, "invalid-request", str(exc)) from exc
        if episode_id:
            record = EpisodeRecord(backends.fhir, tenant_id)
            try:
                stored = await record.add(episode_id, response)
                for o in observations:
                    o["derivedFrom"] = [{"reference": f"QuestionnaireResponse/{stored['id']}"}]
                    await record.add(episode_id, o)
            except (KeyError, ValueError) as exc:
                raise Problem(409, "not-filed", str(exc)) from exc
        return {"resourceType": "Bundle", "type": "collection",
                "entry": [{"resource": o} for o in observations]}

    app.include_router(r)
