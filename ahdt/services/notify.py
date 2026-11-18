"""Notification routing by recipient and consent (design 04, 4.7.5).

A notification reaches a person on the channel they use (app, SMS, USSD or voice) and a
clinician through APDT tasks. It is routed only when the person's consent covers care or
self-management. The router publishes `notification.requested`; the channels service and the
APDT consume it.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, Literal

from atra.backends import Backends
from atra.consent import ConsentRegistry
from atra.contracts import EventEnvelope
from atra.ids import new_record_id

EVENT = "notification.requested"
PERSON_CHANNELS = ("app", "sms", "ussd", "voice")
PURPOSES = frozenset({"care", "self_management"})

type Recipient = Literal["person", "device", "clinician"]


class NotificationRouter:
    def __init__(self, backends: Backends, consents: ConsentRegistry,
                 now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.backends = backends
        self.consents = consents
        self.now = now

    def channel_for(self, recipient: Recipient, channel: str | None) -> str:
        """`apdt` for a clinician, `device` for a device, else the person's channel."""
        if recipient == "clinician":
            return "apdt"
        if recipient == "device":
            return "device"
        return channel if channel in PERSON_CHANNELS else "app"

    def allowed(self, hdt_id: str) -> bool:
        consent = self.consents.get(hdt_id)
        return consent is not None and bool(PURPOSES & set(consent.purposes))

    async def send(self, hdt_id: str, recipient: Recipient, *, channel: str | None = None,
                   **payload: Any) -> str | None:
        """The channel used, or None when consent does not allow the message."""
        if not self.allowed(hdt_id):
            return None
        used = self.channel_for(recipient, channel)
        await self.backends.events.publish(EventEnvelope(
            event_id=new_record_id(), event_type=EVENT, source="ahdt.notify", hdt_id=hdt_id,
            wall_time=self.now(), sim_time=None, trace_id=new_record_id(),
            payload={"to": recipient, "channel": used, **payload}))
        return used
