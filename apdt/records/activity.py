"""Care-team activity: tasks, hand-overs, messages, alerts and acknowledgements.

Rows live in the `activity` table; every change is also published as an event
(`task.created`, `task.completed`, `alert.raised`, `alert.acknowledged`, `alert.escalated`)
so Kafka (p1+) or the in-process bus (p0) carries the log.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select, update

from apdt.records.tables import activity
from atra.backends.base import EventBusBackend, RelationalBackend
from atra.contracts import EventEnvelope
from atra.ids import new_record_id

type ActivityKind = Literal["task", "handover", "message", "alert"]
SOURCE = "apdt"


class ActivityLog:
    def __init__(self, db: RelationalBackend, events: EventBusBackend, tenant_id: str) -> None:
        self.db = db
        self.events = events
        self.tenant_id = tenant_id

    async def _publish(self, event_type: str, row: Mapping[str, Any],
                       payload: Mapping[str, Any]) -> None:
        await self.events.publish(EventEnvelope(
            event_id=new_record_id(), event_type=event_type, source=SOURCE,
            hdt_id=row.get("hdt_id"), tenant_id=self.tenant_id, episode_id=row.get("episode_id"),
            wall_time=datetime.now(UTC), trace_id=new_record_id(), payload=dict(payload)))

    async def _insert(self, kind: ActivityKind, body: Mapping[str, Any], *,
                      hdt_id: str | None, episode_id: str | None, to_role: str | None = None,
                      to_id: str | None = None, due_by: datetime | None = None) -> dict[str, Any]:
        row = {"activity_id": new_record_id(), "tenant_id": self.tenant_id,
               "episode_id": episode_id, "hdt_id": hdt_id, "kind": kind, "status": "open",
               "to_role": to_role, "to_id": to_id, "body": dict(body),
               "created_at": datetime.now(UTC), "due_by": due_by}
        async with self.db.engine().begin() as conn:
            await conn.execute(activity.insert().values(row))
        return row

    async def task(self, description: str, *, hdt_id: str, episode_id: str | None = None,
                   to_role: str | None = None, to_id: str | None = None,
                   due_by: datetime | None = None, focus: str | None = None) -> dict[str, Any]:
        task: dict[str, Any] = {"resourceType": "Task", "status": "requested", "intent": "order",
                                "description": description}
        if focus:
            task["focus"] = {"reference": focus}
        row = await self._insert("task", task, hdt_id=hdt_id, episode_id=episode_id,
                                 to_role=to_role, to_id=to_id, due_by=due_by)
        task["id"] = row["activity_id"]
        await self._publish("task.created", row, task)
        return row

    async def alert(self, *, severity: str, reason: str, to_role: str, to_id: str | None,
                    hdt_id: str, episode_id: str | None, due_by: datetime | None = None,
                    bundle_id: str | None = None) -> dict[str, Any]:
        body = {"severity": severity, "reason": reason, "bundle_id": bundle_id}
        row = await self._insert("alert", body, hdt_id=hdt_id, episode_id=episode_id,
                                 to_role=to_role, to_id=to_id, due_by=due_by)
        await self._publish("alert.raised", row, {
            "alert_id": row["activity_id"], **body, "to": {"role": to_role, "id": to_id},
            "due_by": due_by.isoformat() if due_by else None})
        return row

    async def message(self, text: str, *, hdt_id: str | None, episode_id: str | None,
                      to_role: str | None = None, to_id: str | None = None) -> dict[str, Any]:
        return await self._insert("message", {"text": text}, hdt_id=hdt_id,
                                  episode_id=episode_id, to_role=to_role, to_id=to_id)

    async def handover(self, summary: str, *, episode_id: str, hdt_id: str, from_id: str,
                       to_id: str) -> dict[str, Any]:
        return await self._insert("handover", {"summary": summary, "from": from_id},
                                  hdt_id=hdt_id, episode_id=episode_id, to_id=to_id)

    async def get(self, activity_id: str) -> dict[str, Any]:
        async with self.db.engine().connect() as conn:
            row = (await conn.execute(select(activity).where(
                activity.c.activity_id == activity_id))).mappings().first()
        if row is None:
            raise KeyError(activity_id)
        return dict(row)

    async def _close(self, activity_id: str, status: str, by: str) -> dict[str, Any]:
        async with self.db.engine().begin() as conn:
            await conn.execute(update(activity).where(activity.c.activity_id == activity_id)
                               .values(status=status, closed_at=datetime.now(UTC), closed_by=by))
        return await self.get(activity_id)

    async def complete(self, activity_id: str, *, by: str) -> dict[str, Any]:
        row = await self._close(activity_id, "completed", by)
        await self._publish("task.completed", row, {**row["body"], "id": activity_id,
                                                    "status": "completed"})
        return row

    async def acknowledge(self, alert_id: str, *, by: str) -> dict[str, Any]:
        row = await self._close(alert_id, "acknowledged", by)
        await self._publish("alert.acknowledged", row, {"alert_id": alert_id, "by": by})
        return row

    async def escalate(self, alert_id: str, *, to_role: str, to_id: str | None,
                       level: int) -> dict[str, Any]:
        prev = await self.get(alert_id)
        async with self.db.engine().begin() as conn:
            await conn.execute(update(activity).where(activity.c.activity_id == alert_id)
                               .values(to_role=to_role, to_id=to_id, status="escalated"))
        row = await self.get(alert_id)
        await self._publish("alert.escalated", row, {
            "alert_id": alert_id, "from": {"role": prev["to_role"], "id": prev["to_id"]},
            "to": {"role": to_role, "id": to_id}, "level": level})
        return row

    async def open_items(self, *, kind: ActivityKind | None = None,
                         to_role: str | None = None) -> list[dict[str, Any]]:
        q = select(activity).where(activity.c.tenant_id == self.tenant_id,
                                   activity.c.status.in_(("open", "escalated")))
        if kind:
            q = q.where(activity.c.kind == kind)
        if to_role:
            q = q.where(activity.c.to_role == to_role)
        async with self.db.engine().connect() as conn:
            return [dict(r) for r in (await conn.execute(
                q.order_by(activity.c.created_at))).mappings().all()]
