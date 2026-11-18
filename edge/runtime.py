"""One edge instance: devices in, buffered observations out to the AHDT (design 04, 4.2).

Each `step`:
1. flushes the `DeviceGateway` (WP10), which decodes every frame received since the last step
   into ingestion payloads;
2. pre-processes them (`edge.preprocess`);
3. runs the alert rules and the ONNX edge models on the cleaned readings and closed windows;
4. puts what the link profile allows into the outbox and, when the link is up, drains the
   outbox to the AHDT gRPC `Ingest`;
5. sends the new alerts to the phone, and by SMS when the AHDT cannot be reached.

The edge works the same whether the AHDT answers or not: nothing but delivery depends on it.
"""

from __future__ import annotations

from collections import defaultdict, deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ahdt.ingest.fields import field_index
from atra.backends.base import EventBusBackend, EventHandler
from atra.contracts import Code, EventEnvelope
from edge.actuators.service import ActuationService
from edge.alerts import Alert, AlertDispatcher, AlertRules, Dispatched, from_detections
from edge.bandwidth import Shaper
from edge.config import EdgeSettings
from edge.devices.gateway import DeviceGateway, Sink
from edge.devices.transport import Transports
from edge.inference import Detection, OnnxHost
from edge.outbox import DrainResult, Forwarder, Ingestor, Outbox
from edge.preprocess import FeatureWindow, Preprocessor
from edge.registry import DeviceRecord, DeviceRegistry
from edge.uplink import GrpcIngestor

HISTORY_WINDOWS = 4 * 1440

class _Collector(EventBusBackend):
    """Takes the gateway's `ingest.<twin>` events in place of a bus."""

    def __init__(self) -> None:
        self.payloads: list[dict[str, Any]] = []

    async def publish(self, event: EventEnvelope) -> None:
        twin = event.event_type.split(".", 1)[1]
        dt = "" if twin == "unrouted" else twin
        self.payloads += [{**o, "dt": dt} for o in event.payload["observations"]]

    def subscribe(self, pattern: str, handler: EventHandler) -> None:
        raise NotImplementedError("the edge passes gateway events straight to its pipeline")

    async def close(self) -> None:
        return None

    def take(self) -> list[dict[str, Any]]:
        out, self.payloads = self.payloads, []
        return out


def twin_of(code: Code) -> str | None:
    ref = field_index().resolve(code)
    return ref.twin.value if ref else None


@dataclass
class StepResult:
    readings: int = 0
    dropouts: int = 0
    enqueued: int = 0
    features: list[FeatureWindow] = field(default_factory=list)
    detections: list[Detection] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    dispatched: list[Dispatched] = field(default_factory=list)
    drain: DrainResult = field(default_factory=DrainResult)
    cloud_reachable: bool = True


class _NoSink:
    async def observations(self, fmt: str, body: bytes) -> Any:
        raise RuntimeError("this edge has no AHDT batch sink")

    async def dicom(self, body: bytes) -> Any:
        raise RuntimeError("this edge has no AHDT batch sink")

    async def vcf(self, body: bytes, *, hdt_id: str) -> Any:
        raise RuntimeError("this edge has no AHDT batch sink")

    async def media(self, body: bytes, *, hdt_id: str, content_type: str) -> Any:
        raise RuntimeError("this edge has no AHDT batch sink")


class EdgeRuntime:
    def __init__(self, settings: EdgeSettings, *, registry: DeviceRegistry, outbox: Outbox,
                 ingestor: Ingestor, models: OnnxHost | None = None,
                 rules: AlertRules | None = None, actuation: ActuationService | None = None,
                 dispatcher: AlertDispatcher | None = None, sink: Sink | None = None,
                 transports: Transports | None = None,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.settings = settings
        self.registry = registry
        self.outbox = outbox
        self.ingestor = ingestor
        self.forwarder = Forwarder(outbox, ingestor, batch_size=settings.batch_size)
        self.models = models or OnnxHost()
        self.rules = rules or AlertRules()
        self.dispatcher = dispatcher
        self.clock = clock
        self.preprocessor = Preprocessor(window_s=settings.feature_window_s)
        self.shaper = Shaper(settings.link, window_s=settings.feature_window_s)
        self._collector = _Collector()
        self.gateway = DeviceGateway(self._collector, sink or _NoSink(), twin_of=twin_of,
                                     transports=transports, actuation=actuation, clock=clock)
        self.cloud_reachable = True
        self._history: dict[str, deque[FeatureWindow]] = defaultdict(
            lambda: deque(maxlen=HISTORY_WINDOWS))
        registry.on_register(self._register)

    def _register(self, record: DeviceRecord) -> None:
        self.gateway.register(record.device_id, record.hdt_id, record.device_class)

    @property
    def transports(self) -> Transports:
        return self.gateway.transports

    def set_link(self, profile: str) -> int:
        """Change the link profile; returns the readings released from `2g` windows."""
        return self.outbox.enqueue(self.shaper.set_link(profile))

    async def deliver(self) -> DrainResult:
        link = self.shaper.link
        if not link.deliver:
            return DrainResult(link_down=True)
        if isinstance(self.ingestor, GrpcIngestor):
            self.ingestor.compression = link.compression
        result = await self.forwarder.drain(batch_size=link.batch_size)
        self.cloud_reachable = not result.link_down
        return result

    async def step(self) -> StepResult:
        now = self.clock()
        await self.gateway.flush()
        batch = self.preprocessor.process(self._collector.take(), now)
        result = StepResult(readings=len(batch.payloads), dropouts=batch.dropouts,
                            features=batch.features)
        for w in batch.features:
            self._history[w.hdt_id].append(w)
        result.detections = (self.models.on_features(batch.features)
                             + self.models.on_waveforms(batch.payloads))
        result.alerts = self.rules.evaluate(batch.payloads) + from_detections(result.detections)
        result.enqueued = self.outbox.enqueue(self.shaper.select(batch, now))
        result.drain = await self.deliver()
        result.cloud_reachable = not result.drain.link_down
        if self.dispatcher is not None and result.alerts:
            sms = self.shaper.link.sms_alerts or not result.cloud_reachable
            result.dispatched = await self.dispatcher.dispatch(result.alerts, sms=sms)
        return result

    def history(self, hdt_id: str) -> list[FeatureWindow]:
        """The person's latest closed feature windows, oldest first."""
        return list(self._history.get(hdt_id, ()))

    def status(self) -> Mapping[str, Any]:
        counts = self.outbox.counts()
        return {"pending": counts["pending"], "acked": counts["acked"],
                "rejected": counts["rejected"], "oldest": self.outbox.oldest_pending(),
                "link": self.shaper.link.profile, "cloud_reachable": self.cloud_reachable}
