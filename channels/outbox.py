"""Store-and-forward SMS outbox with an audit record for every message (design 05, 5.3).

A message is tried at once. When the provider fails or refuses it, the message stays
queued and `flush()` retries it with doubling back-off until `max_attempts`. Delivery
reports update the status. Every attempt, inbound message and delivery report is written
to the service's audit chain and published as `message.sent` / `message.received`; both
carry the phone reference and a text reference, never the number or the text.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal, Protocol

from atra.backends.base import EventBusBackend
from atra.contracts import EventEnvelope
from atra.ids import uuid7
from atra.provenance import AuditLog
from channels.africastalking import FINAL_DELIVERY, SmsError, SmsResult

type Status = Literal["queued", "sent", "delivered", "failed"]
CHANNEL_ACTOR = {"id": "channels", "role": "system"}


class SmsSender(Protocol):
    async def send(self, numbers: Sequence[str], message: str) -> list[SmsResult]: ...


@dataclass
class OutboundMessage:
    message_id: str
    to_ref: str
    phone: str = field(repr=False)
    text: str = field(repr=False)
    language: str
    purpose: str
    tenant_id: str | None = None
    hdt_id: str | None = None
    status: Status = "queued"
    attempts: int = 0
    provider_id: str | None = None
    next_try: float = 0.0
    last_error: str | None = None


class SimulatedSms:
    """The SMS provider of the simulator and the tests: keeps each phone's inbox."""

    def __init__(self) -> None:
        self.inbox: dict[str, list[str]] = {}
        self.online = True
        self._lock = threading.Lock()

    async def send(self, numbers: Sequence[str], message: str) -> list[SmsResult]:
        if not self.online:
            raise SmsError("the simulated network is offline")
        out = []
        with self._lock:
            for n in numbers:
                self.inbox.setdefault(n, []).append(message)
                out.append(SmsResult(n, 101, "Success", f"SIM-{uuid7().hex[:12]}"))
        return out


class Outbox:
    def __init__(self, sender: SmsSender, audit: AuditLog, events: EventBusBackend, *,
                 ref: Callable[[str], str], max_attempts: int = 5, backoff_s: float = 30.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.sender, self.audit, self.events, self.ref = sender, audit, events, ref
        self.max_attempts, self.backoff_s, self.clock = max_attempts, backoff_s, clock
        self.messages: dict[str, OutboundMessage] = {}
        self._lock = threading.Lock()

    async def _event(self, event_type: str, payload: dict[str, str], *,
                     tenant_id: str | None, hdt_id: str | None) -> None:
        await self.events.publish(EventEnvelope(
            event_id=f"evt-{uuid7()}", event_type=event_type, source="channels",
            hdt_id=hdt_id, tenant_id=tenant_id, wall_time=datetime.now(UTC),
            trace_id=uuid7().hex, payload=payload))

    async def enqueue(self, phone: str, text: str, *, language: str, purpose: str,
                      tenant_id: str | None = None, hdt_id: str | None = None) -> OutboundMessage:
        msg = OutboundMessage(f"msg-{uuid7()}", self.ref(phone), phone, text, language, purpose,
                              tenant_id, hdt_id)
        with self._lock:
            self.messages[msg.message_id] = msg
        await self._try(msg)
        return msg

    async def _try(self, msg: OutboundMessage) -> None:
        msg.attempts += 1
        try:
            results = await self.sender.send([msg.phone], msg.text)
            result = next((r for r in results if r.number == msg.phone), None)
            if result is None or not result.accepted:
                raise SmsError(result.status if result else "no recipient result")
        except SmsError as exc:
            msg.last_error = str(exc)
            if msg.attempts >= self.max_attempts:
                msg.status = "failed"
            else:
                msg.next_try = self.clock() + self.backoff_s * 2 ** (msg.attempts - 1)
            self.audit.append(actor=CHANNEL_ACTOR, action="sms.send", target=msg.message_id,
                              purpose=msg.purpose, outcome="error", reason=str(exc),
                              tenant_id=msg.tenant_id, hdt_id=msg.hdt_id)
            return
        msg.status, msg.provider_id, msg.last_error = "sent", result.message_id, None
        self.audit.append(actor=CHANNEL_ACTOR, action="sms.send", target=msg.message_id,
                          purpose=msg.purpose, outcome="ok", tenant_id=msg.tenant_id,
                          hdt_id=msg.hdt_id)
        await self._event("message.sent", {
            "channel": "sms", "language": msg.language, "to": msg.to_ref,
            "text_ref": f"channels:message/{msg.message_id}"},
            tenant_id=msg.tenant_id, hdt_id=msg.hdt_id)

    async def flush(self) -> int:
        """Retries the queued messages that are due; returns how many were tried."""
        now = self.clock()
        with self._lock:
            due = [m for m in self.messages.values()
                   if m.status == "queued" and m.attempts and m.next_try <= now]
        for m in due:
            await self._try(m)
        return len(due)

    def pending(self) -> list[OutboundMessage]:
        with self._lock:
            return [m for m in self.messages.values() if m.status == "queued"]

    def delivery_report(self, provider_id: str, status: str,
                        failure_reason: str | None = None) -> OutboundMessage | None:
        with self._lock:
            msg = next((m for m in self.messages.values() if m.provider_id == provider_id), None)
        if msg is None:
            return None
        if status == "Success":
            msg.status = "delivered"
        elif status in FINAL_DELIVERY:
            msg.status, msg.last_error = "failed", failure_reason or status
        self.audit.append(actor=CHANNEL_ACTOR, action="sms.delivery", target=msg.message_id,
                          purpose=msg.purpose,
                          outcome="ok" if status not in FINAL_DELIVERY or status == "Success"
                          else "error", reason=failure_reason, tenant_id=msg.tenant_id,
                          hdt_id=msg.hdt_id)
        return msg

    async def received(self, channel: str, from_ref: str, message_id: str, *, language: str,
                       tenant_id: str | None, hdt_id: str | None, purpose: str = "care") -> None:
        self.audit.append(actor={"id": from_ref, "role": "patient" if hdt_id else "system"},
                          action=f"{channel}.receive", target=message_id, purpose=purpose,
                          outcome="ok", tenant_id=tenant_id, hdt_id=hdt_id)
        await self._event("message.received", {
            "channel": channel, "language": language, "from": from_ref,
            "text_ref": f"channels:message/{message_id}"}, tenant_id=tenant_id, hdt_id=hdt_id)
