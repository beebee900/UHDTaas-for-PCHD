"""Receiving side of the connectors of one HDT (design 04, section 4.8).

Each receiving twin has a `ReorderBuffer`: it holds a delivered message for the reorder
window (2 s) and then hands it on in `(sim_time, hlc)` order. The inbox keeps the latest
payload per incoming connector, which is what `connector:` model ports read
(`ahdt.models.coupling.resolve_inputs(connectors=inbox.payloads(kind))`), and calls the
twin's ingestion hooks.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from atra.backends.base import EventBusBackend
from atra.clock import HLCStamp
from atra.connectors import Connector, DTKind, Message
from atra.contracts import EventEnvelope
from atra.ids import new_record_id

log = logging.getLogger("ahdt.coupling")

REORDER_WINDOW_S = 2.0


@dataclass(frozen=True)
class Delivery:
    connector: str
    name: str
    source: DTKind
    receiver: DTKind
    topic: str
    message: Message

    @property
    def stamp(self) -> HLCStamp:
        text = self.message.provenance.get("hlc")
        try:
            return HLCStamp.parse(text) if isinstance(text, str) else HLCStamp(0, 0, "")
        except ValueError:
            return HLCStamp(0, 0, "")

    @property
    def key(self) -> tuple[float, HLCStamp]:
        sim = self.message.sim_time
        return (float("-inf") if sim is None else float(sim), self.stamp)


type Release = Callable[[Delivery], Awaitable[None]]
type Hook = Callable[[Delivery], Awaitable[None]]


@dataclass
class _Held:
    arrival: float
    delivery: Delivery


class ReorderBuffer:
    """Releases each message `window_s` after arrival, in `(sim_time, hlc)` order."""

    def __init__(self, release: Release, *, window_s: float = REORDER_WINDOW_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.release = release
        self.window_s = window_s
        self.clock = clock
        self._held: list[_Held] = []
        self._timer: asyncio.Task[None] | None = None

    def __len__(self) -> int:
        return len(self._held)

    async def add(self, delivery: Delivery) -> None:
        self._held.append(_Held(self.clock(), delivery))
        if self.window_s <= 0:
            await self.release_due()
        elif self._timer is None or self._timer.done():
            self._timer = asyncio.create_task(self._run())

    async def release_due(self, *, everything: bool = False) -> int:
        cutoff = self.clock() - self.window_s
        due = [h for h in self._held if everything or h.arrival <= cutoff]
        if not due:
            return 0
        released = {id(h) for h in due}
        self._held = [h for h in self._held if id(h) not in released]
        for held in sorted(due, key=lambda h: h.delivery.key):
            await self.release(held.delivery)
        return len(due)

    async def _run(self) -> None:
        while self._held:
            first = min(h.arrival for h in self._held)
            await asyncio.sleep(max(0.0, first + self.window_s - self.clock()))
            await self.release_due()

    async def flush(self) -> int:
        """Release everything held now, in order (used on stop)."""
        if self._timer is not None and not self._timer.done():
            self._timer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._timer
        self._timer = None
        return await self.release_due(everything=True)


@dataclass
class CouplingInbox:
    """Latest connector payloads and ingestion hooks of every twin of one HDT."""

    hdt_id: str
    window_s: float = REORDER_WINDOW_S
    events: EventBusBackend | None = None
    latest: dict[DTKind, dict[str, dict[str, Any]]] = field(default_factory=dict)
    by_source: dict[DTKind, dict[str, dict[DTKind, dict[str, Any]]]] = field(
        default_factory=dict)
    delivered: list[Delivery] = field(default_factory=list)
    _hooks: dict[DTKind, list[Hook]] = field(default_factory=dict)
    _buffers: dict[DTKind, ReorderBuffer] = field(default_factory=dict)

    def on(self, kind: DTKind, hook: Hook) -> None:
        """Register an ingestion hook of the twin `kind`."""
        self._hooks.setdefault(kind, []).append(hook)

    def buffer(self, kind: DTKind) -> ReorderBuffer:
        if kind not in self._buffers:
            self._buffers[kind] = ReorderBuffer(self._release, window_s=self.window_s)
        return self._buffers[kind]

    def deliver_fn(self, connector: Connector, spec_name: str, *,
                   to_source: bool) -> Callable[[Message], Awaitable[None]]:
        sender = connector.target.kind if to_source else connector.source.kind
        receiver = connector.source.kind if to_source else connector.target.kind
        topic = connector.topic("in" if to_source else "out")

        async def deliver(msg: Message) -> None:
            await self.buffer(receiver).add(
                Delivery(spec_name, connector.name, sender, receiver, topic, msg))

        return deliver

    def payloads(self, kind: DTKind) -> dict[str, dict[str, Any]]:
        """`{connector name: latest payload}` received by `kind`."""
        return dict(self.latest.get(kind, {}))

    async def flush(self) -> int:
        return sum([await b.flush() for b in self._buffers.values()])

    async def _release(self, d: Delivery) -> None:
        self.latest.setdefault(d.receiver, {})[d.connector] = dict(d.message.payload)
        self.by_source.setdefault(d.receiver, {}).setdefault(d.connector, {})[d.source] = dict(
            d.message.payload)
        self.delivered.append(d)
        for hook in self._hooks.get(d.receiver, []):
            try:
                await hook(d)
            except Exception:  # one twin's hook must not stop delivery to the others
                log.exception("ingestion hook of %s failed", d.receiver.value)
        await self._event("connector.delivered", d.message.trace_id, d.message.sim_time,
                          {"connector": d.name, "message_id": d.message.msg_id,
                           "topic": d.topic})

    async def dead_lettered(self, record: Mapping[str, Any]) -> None:
        message = record.get("message")
        msg_id = message.get("msg_id") if isinstance(message, dict) else None
        trace = message.get("trace_id") if isinstance(message, dict) else None
        await self._event("connector.dead_lettered", trace or new_record_id(), None,
                          {"connector": record["connector"], "message_id": msg_id,
                           "topic": record["topic"], "reason": record["reason"]})

    async def _event(self, event_type: str, trace_id: str, sim_time: float | None,
                     payload: dict[str, Any]) -> None:
        if self.events is None:
            return
        try:
            await self.events.publish(EventEnvelope(
                event_id=new_record_id(), event_type=event_type, source="ahdt.coupling",
                hdt_id=self.hdt_id, wall_time=datetime.now(UTC), sim_time=sim_time,
                trace_id=trace_id, payload=payload))
        except Exception:  # events are best effort; the message itself is already handled
            log.exception("could not publish %s", event_type)
