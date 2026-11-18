"""Automatic explanation on decision thresholds (design 04, 4.7.4).

The worker listens for `observation.ingested`. A reading beyond the warning limits of its
field makes the worker refresh the twin's state, and `XaiTools` explains the state when it
reaches `watch`. A twin is refreshed at most once per cooldown.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

from ahdt.services import Services
from ahdt.services.model import field_status
from atra.connectors import DTKind
from atra.contracts import EventEnvelope

log = logging.getLogger("ahdt.auto_explain")

COOLDOWN_S = 300.0


class AutoExplainWorker:
    def __init__(self, services: Services, *, cooldown_s: float = COOLDOWN_S,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.services = services
        self.cooldown_s = cooldown_s
        self.clock = clock
        self._last: dict[tuple[str, str], float] = {}

    def subscribe(self) -> None:
        self.services.runtime.backends.events.subscribe("observation.ingested", self.handle)

    async def handle(self, event: EventEnvelope) -> None:
        payload = event.payload
        value = payload.get("value")
        if event.hdt_id is None or not isinstance(value, int | float):
            return
        kind = DTKind(payload["dt"])
        ref = self._range(kind, str(payload["field"]))
        if ref is None or field_status(ref, float(value)) == "normal":
            return
        key = (event.hdt_id, kind.value)
        now = self.clock()
        if now - self._last.get(key, -self.cooldown_s) < self.cooldown_s:
            return
        self._last[key] = now
        try:
            await self.services.model.state_of(event.hdt_id, kind)
        except Exception:
            log.warning("state refresh of %s for %s failed", kind.value, event.hdt_id,
                        exc_info=True)

    def _range(self, kind: DTKind, name: str) -> dict[str, float | None] | None:
        definition = self.services.runtime.registry.get(kind)
        field = next((f for f in definition.fields if f.name == name), None) \
            if definition else None
        found = self.services.model.reference_range(field.ref if field else None)
        return dict(found) if found is not None else None
