"""Patient agency record: goals of care, preferences, MCDA weights, proxy, consent decisions
and the patient's own questions. FHIR resources live in the tenant partition; weights and
the question log live in the `agency_*` tables."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select, update

from apdt.records.episodes import PATIENT_SYSTEM
from apdt.records.tables import agency_questions, agency_weights
from atra.backends.base import FhirBackend, RelationalBackend
from atra.consent import to_fhir
from atra.contracts import PurposeOfUse
from atra.ids import new_record_id

AGENCY_TYPES = ("Goal", "Consent", "QuestionnaireResponse", "RelatedPerson")


class AgencyRecord:
    def __init__(self, fhir: FhirBackend, db: RelationalBackend, tenant_id: str) -> None:
        self.fhir = fhir
        self.db = db
        self.tenant_id = tenant_id

    def _patient(self, hdt_id: str) -> dict[str, Any]:
        return {"identifier": {"system": PATIENT_SYSTEM, "value": hdt_id}}

    async def _create(self, body: dict[str, Any]) -> dict[str, Any]:
        return await self.fhir.create({"id": new_record_id(), **body}, partition=self.tenant_id)

    async def goal(self, hdt_id: str, text: str, *, priority: str = "medium-priority",
                   target: Mapping[str, Any] | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "resourceType": "Goal", "lifecycleStatus": "active", "subject": self._patient(hdt_id),
            "description": {"text": text},
            "priority": {"coding": [{"system": "http://terminology.hl7.org/CodeSystem/goal-priority",
                                     "code": priority}]}}
        if target:
            body["target"] = [dict(target)]
        return await self._create(body)

    async def answers(self, hdt_id: str, questionnaire: str,
                      items: Mapping[str, Any]) -> dict[str, Any]:
        def answer(v: Any) -> dict[str, Any]:
            if isinstance(v, bool):
                return {"valueBoolean": v}
            if isinstance(v, int):
                return {"valueInteger": v}
            if isinstance(v, float):
                return {"valueDecimal": v}
            return {"valueString": str(v)}
        return await self._create({
            "resourceType": "QuestionnaireResponse", "status": "completed",
            "questionnaire": f"https://atra.health/fhir/Questionnaire/{questionnaire}",
            "subject": self._patient(hdt_id), "authored": datetime.now(UTC).isoformat(),
            "item": [{"linkId": k, "answer": [answer(v)]} for k, v in items.items()]})

    async def proxy(self, hdt_id: str, name: str, relationship: str,
                    phone: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {
            "resourceType": "RelatedPerson", "active": True, "patient": self._patient(hdt_id),
            "name": [{"text": name}],
            "relationship": [{"coding": [{
                "system": "http://terminology.hl7.org/CodeSystem/v3-RoleCode",
                "code": relationship}]}]}
        if phone:
            body["telecom"] = [{"system": "phone", "value": phone}]
        return await self._create(body)

    async def consent(self, hdt_id: str, purposes: Iterable[PurposeOfUse | str],
                      refused_tools: Iterable[str] = (),
                      actors: Iterable[Mapping[str, str]] = ()) -> dict[str, Any]:
        consent = to_fhir(hdt_id, purposes, refused_tools, consent_id=new_record_id(),
                          actors=actors)
        return await self.fhir.create(consent, partition=self.tenant_id)

    async def resources(self, hdt_id: str, resource_type: str) -> list[dict[str, Any]]:
        if resource_type not in AGENCY_TYPES:
            raise ValueError(f"{resource_type} is not an agency resource")
        key = "patient" if resource_type in ("RelatedPerson", "Consent") else "subject"
        return [r for r in await self.fhir.search(resource_type, partition=self.tenant_id)
                if _refers_to(r.get(key, {}), hdt_id)]

    async def set_weights(self, hdt_id: str, weights: Mapping[str, float], *,
                          method: str) -> None:
        total = sum(weights.values())
        if total <= 0:
            raise ValueError("weights must have a positive sum")
        now = datetime.now(UTC)
        async with self.db.engine().begin() as conn:
            await conn.execute(delete(agency_weights).where(
                agency_weights.c.tenant_id == self.tenant_id, agency_weights.c.hdt_id == hdt_id))
            await conn.execute(agency_weights.insert(), [
                {"tenant_id": self.tenant_id, "hdt_id": hdt_id, "criterion": c,
                 "weight": w / total, "method": method, "recorded_at": now}
                for c, w in weights.items()])

    async def weights(self, hdt_id: str) -> dict[str, float]:
        async with self.db.engine().connect() as conn:
            rows = (await conn.execute(select(agency_weights.c.criterion, agency_weights.c.weight)
                    .where(agency_weights.c.tenant_id == self.tenant_id,
                           agency_weights.c.hdt_id == hdt_id))).all()
        return {r.criterion: r.weight for r in rows}

    async def ask(self, hdt_id: str, text: str, *, channel: str,
                  episode_id: str | None = None) -> str:
        qid = new_record_id()
        async with self.db.engine().begin() as conn:
            await conn.execute(agency_questions.insert().values(
                question_id=qid, tenant_id=self.tenant_id, hdt_id=hdt_id, episode_id=episode_id,
                channel=channel, text=text, asked_at=datetime.now(UTC)))
        return qid

    async def answer(self, question_id: str, answer: str) -> None:
        async with self.db.engine().begin() as conn:
            await conn.execute(update(agency_questions)
                               .where(agency_questions.c.question_id == question_id)
                               .values(answer=answer, answered_at=datetime.now(UTC)))

    async def questions(self, hdt_id: str, *, open_only: bool = False) -> list[dict[str, Any]]:
        q = select(agency_questions).where(agency_questions.c.tenant_id == self.tenant_id,
                                           agency_questions.c.hdt_id == hdt_id)
        if open_only:
            q = q.where(agency_questions.c.answer.is_(None))
        async with self.db.engine().connect() as conn:
            return [dict(r) for r in (await conn.execute(
                q.order_by(agency_questions.c.asked_at))).mappings().all()]


def _refers_to(ref: Mapping[str, Any], hdt_id: str) -> bool:
    """A patient reference by HDT identifier or by `Patient/<hdt_id>` (atra.consent form)."""
    return (ref.get("identifier", {}).get("value") == hdt_id
            or ref.get("reference") == f"Patient/{hdt_id}")
