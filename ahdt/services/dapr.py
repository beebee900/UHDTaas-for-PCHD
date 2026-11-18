"""Dapr pub/sub bridge of the AHDT process (design 04, 4.7.1).

Inbound: Dapr delivers the topics named by `deploy/dapr/subscription-*.yaml` as CloudEvents
to `POST /dapr/events/{topic}`; the data becomes an event on the in-process bus, where the
ingest pipeline and the services consume it. Outbound: events of the types in `PUBLISHED`
go to the sidecar's publish API when `DAPR_HTTP_PORT` is set. Without a sidecar the
bridge does nothing and the in-process bus carries the events alone.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx
from fastapi import FastAPI, Request

from atra.backends import Backends
from atra.contracts import EventEnvelope
from atra.service import Problem

log = logging.getLogger("ahdt.dapr")

PUBSUB = "atra-pubsub"
PUBLISHED = ("observation.ingested", "model.drift_detected", "explanation.created",
             "notification.requested")
INBOUND = ("observation.ingested", "notification.requested")


def publish_url(port: str) -> str:
    return f"http://127.0.0.1:{port}/v1.0/publish/{PUBSUB}"


class DaprPublisher:
    def __init__(self, backends: Backends, *, port: str | None = None,
                 client: httpx.AsyncClient | None = None) -> None:
        self.port = port if port is not None else os.environ.get("DAPR_HTTP_PORT")
        self.client = client or httpx.AsyncClient(timeout=5.0)
        self.relayed: set[str] = set()
        if self.port:
            for kind in PUBLISHED:
                backends.events.subscribe(kind, self.relay)

    async def relay(self, event: EventEnvelope) -> None:
        if event.event_id in self.relayed or event.source == "dapr":
            return
        self.relayed.add(event.event_id)
        try:
            resp = await self.client.post(
                f"{publish_url(str(self.port))}/{event.event_type}",
                content=event.model_dump_json(),
                headers={"content-type": "application/cloudevents+json"})
            resp.raise_for_status()
        except httpx.HTTPError:
            log.warning("publishing %s to Dapr failed", event.event_type, exc_info=True)


def mount_dapr(app: FastAPI, backends: Backends) -> None:
    app.state.dapr = DaprPublisher(backends)

    @app.post("/dapr/events/{topic}", tags=["dapr"], include_in_schema=False)
    async def inbound(topic: str, request: Request) -> dict[str, str]:
        if topic not in INBOUND:
            raise Problem(404, "not-found", f"topic {topic} is not consumed here")
        body: dict[str, Any] = await request.json()
        data = body.get("data", body)
        try:
            event = EventEnvelope.model_validate({**data, "source": "dapr"})
        except ValueError as exc:
            raise Problem(422, "invalid-arguments", str(exc)) from exc
        await backends.events.publish(event)
        return {"status": "SUCCESS"}
