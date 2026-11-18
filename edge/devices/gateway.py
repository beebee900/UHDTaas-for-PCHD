"""The edge device gateway: transports in, ingestion payloads out (design 04, 4.2.2 topic
routing `dev/{hdt_id}/{device_id}/{class}` → edge decoder → AHDT ingest `ingest.{dt}`).

Readings from every device class become the ingestion payloads of
`edge.devices.decode.observations`; `flush` publishes them on the event bus as
`ingest.{twin}` events, one per twin, and passes whole documents (HL7 v2, FHIR Bundles,
DICOM, VCF, media) to the AHDT batch sink. A frame that does not decode is kept in
`dead_letters` with its reason and never reaches ingestion.

Device clocks of the BLE and 11073 devices carry no time zone; devices are set to UTC, so
naive times are read as UTC.

With an `ActuationService`, the gateway also takes actuator commands on `act/{hdt_id}/...`
(design 04, 4.1.2); `flush` passes them through the autonomy check before anything reaches a
device.
"""

from __future__ import annotations

import asyncio
import dataclasses
import email.parser
import email.policy
import json
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

import numpy as np

from atra.backends.base import EventBusBackend
from atra.contracts import Code, EventEnvelope
from atra.ids import new_record_id
from edge.actuators.catalogue import ACT_TOPIC
from edge.actuators.service import ActuationResult, ActuationService
from edge.devices.decode import environment, gait, gatt, media, phd, self_report, streams, wfdb
from edge.devices.decode.gatt import heart_rate
from edge.devices.decode.observations import (
    CodedReading,
    Reading,
    field_reading,
    from_gatt,
    from_phd,
    payload,
)
from edge.devices.decode.phd import (
    ACCEPTED,
    ACCEPTED_UNKNOWN_CONFIG,
    STANDARD,
    AssociationRequest,
    ConfigReport,
    ConfigReportResponse,
    Configuration,
    EventReport,
    ReleaseRequest,
    ReleaseResponse,
    ScanReportFixed,
)
from edge.devices.decode.phd import nomenclature as nom
from edge.devices.transport import PhdLink, Transports
from edge.devices.transport import coap as coap_codec
from edge.devices.transport.mqtt import Publish

DEVICE_TOPIC = "dev/+/+/+"
MANAGER_SYSTEM_ID = bytes.fromhex("0000000000a71a01")
DICOM_MEDIA = "application/dicom"
LEAD_II_NAMES = frozenset({"II", "MLII"})
SELF_REPORT_CODES = frozenset({"44261-6", "70274-6"})

AnyReading = Reading | CodedReading


type PoseTracker = Callable[[bytes, str], gait.PoseTrack]


def mediapipe_tracker(body: bytes, content_type: str) -> gait.PoseTrack:
    from edge.devices.decode import pose

    return pose.track_bytes(body, content_type)


class Sink(Protocol):
    """AHDT batch import, as `ahdt.devices.sink.EdgeSink` implements it."""

    async def observations(self, fmt: str, body: bytes) -> Any: ...

    async def dicom(self, body: bytes) -> Any: ...

    async def vcf(self, body: bytes, *, hdt_id: str) -> Any: ...

    async def media(self, body: bytes, *, hdt_id: str, content_type: str) -> Any: ...


@dataclass(frozen=True)
class Device:
    device_id: str
    hdt_id: str
    device_class: str


@dataclass
class _Upload:
    kind: str
    body: bytes
    hdt_id: str | None = None
    content_type: str | None = None
    device_id: str | None = None


@dataclass
class _Association:
    config: Configuration | None = None


@dataclass
class FlushResult:
    observations: int = 0
    uploads: list[Any] = field(default_factory=list)
    actuations: list[ActuationResult] = field(default_factory=list)


def _utc(r: AnyReading) -> AnyReading:
    if r.time is not None and r.time.tzinfo is None:
        return dataclasses.replace(r, time=r.time.replace(tzinfo=UTC))
    return r


def stow_parts(body: bytes, content_type: str) -> list[bytes]:
    """The DICOM instances of a STOW-RS request body: `multipart/related;
    type="application/dicom"` (DICOM PS3.18, Store Transaction)."""
    if "multipart/related" not in content_type or DICOM_MEDIA not in content_type:
        raise ValueError("STOW-RS bodies are multipart/related of application/dicom")
    message = email.parser.BytesParser(policy=email.policy.HTTP).parsebytes(
        f"Content-Type: {content_type}\r\n\r\n".encode() + body)
    parts = [p.get_payload(decode=True) for p in message.iter_parts()
             if p.get_content_type() == DICOM_MEDIA]
    return [p for p in parts if isinstance(p, bytes)]


class DeviceGateway:
    def __init__(self, events: EventBusBackend, sink: Sink, *,
                 twin_of: Callable[[Code], str | None], transports: Transports | None = None,
                 actuation: ActuationService | None = None,
                 pose_tracker: PoseTracker = mediapipe_tracker,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.events = events
        self.sink = sink
        self.twin_of = twin_of
        self.transports = transports or Transports()
        self.clock = clock
        self.devices: dict[str, Device] = {}
        self.dead_letters: list[tuple[str, str]] = []
        self._pending: list[dict[str, Any]] = []
        self._uploads: list[_Upload] = []
        self._assoc: dict[str, _Association] = {}
        t = self.transports
        t.mqtt.subscribe(DEVICE_TOPIC, self._on_mqtt)
        t.mqtt.subscribe(environment.UPLINK_TOPIC, self._on_uplink)
        t.ble.subscribe(self._on_ble)
        t.phd = PhdLink(self._on_apdu)
        self.actuation = actuation
        self.pose_tracker = pose_tracker
        if actuation is not None:
            t.mqtt.subscribe(ACT_TOPIC, actuation.on_mqtt)

    def register(self, device_id: str, hdt_id: str, device_class: str) -> Device:
        device = Device(device_id, hdt_id, device_class)
        self.devices[device_id] = device
        if device_class == "environmental":
            self.transports.coap.resource(f"env/{device_id}", self._coap_handler(device))
        return device

    def _emit(self, device: Device, readings: list[AnyReading],
              received: datetime | None = None) -> None:
        received = received or self.clock()
        for r in readings:
            self._pending.append(payload(_utc(r), hdt_id=device.hdt_id,
                                         device_id=device.device_id, received=received))

    def _dead(self, source: str, exc: Exception) -> None:
        self.dead_letters.append((source, f"{type(exc).__name__}: {exc}"))

    def _on_mqtt(self, message: Publish) -> None:
        _, hdt_id, device_id, device_class = message.topic.split("/")
        device = self.devices.get(device_id)
        if device is None or device.hdt_id != hdt_id:
            self._dead(message.topic, LookupError("unregistered device"))
            return
        try:
            self._emit(device, list(streams.decode(device_class, message.payload)))
        except (ValueError, KeyError, TypeError) as exc:
            self._dead(message.topic, exc)

    def _on_uplink(self, message: Publish) -> None:
        try:
            event = json.loads(message.payload)
            dev_eui = environment.uplink(event).dev_eui
            device = self.devices[dev_eui]
            self._emit(device, list(environment.lora_air(event).readings()))
        except (ValueError, KeyError) as exc:
            self._dead(message.topic, exc)

    def _coap_handler(self, device: Device) -> Callable[[coap_codec.Message], int]:
        def handle(request: coap_codec.Message) -> int:
            if request.content_format != coap_codec.APPLICATION_JSON:
                return coap_codec.UNSUPPORTED_CONTENT_FORMAT
            try:
                self._emit(device, list(environment.coap_payload(request.payload).readings()))
            except (ValueError, KeyError) as exc:
                self._dead(f"coap:{device.device_id}", exc)
                return coap_codec.NOT_FOUND
            return coap_codec.CHANGED
        return handle

    def _on_ble(self, device_id: str, uuid: int, value: bytes, at: datetime | None) -> None:
        try:
            m = gatt.decode(uuid, value)
            readings: list[AnyReading] = list(from_gatt(m))
            if isinstance(m, heart_rate.HeartRateMeasurement) and len(m.rr_seconds) >= 3:
                rr_ms = np.asarray(m.rr_seconds) * 1000
                rmssd = float(np.sqrt(np.mean(np.diff(rr_ms) ** 2)))
                readings += field_reading("hrv_rmssd", rmssd, "ms", at)
            self._emit(self.devices[device_id], readings, at)
        except (ValueError, KeyError, TypeError) as exc:
            self._dead(f"ble:{device_id}:0x{uuid:04X}", exc)

    def _on_apdu(self, device_id: str, data: bytes) -> bytes | None:
        """The manager side of an 11073-20601 association."""
        try:
            apdu = phd.decode(data)
            device = self.devices[device_id]
        except (ValueError, KeyError) as exc:
            self._dead(f"phd:{device_id}", exc)
            return phd.encode(phd.Abort(0))
        state = self._assoc.setdefault(device_id, _Association())
        if isinstance(apdu, AssociationRequest):
            info = apdu.phd
            known = info is not None and info.dev_config_id in STANDARD
            state.config = STANDARD[info.dev_config_id] if known and info else None
            return phd.encode(phd.association_response(
                ACCEPTED if known else ACCEPTED_UNKNOWN_CONFIG, MANAGER_SYSTEM_ID))
        if isinstance(apdu, EventReport):
            if apdu.event_type == nom.MDC_NOTI_CONFIG.term:
                report = ConfigReport.decode(apdu.event_info)
                state.config = Configuration.from_report(report)
                return phd.encode(phd.acknowledge(
                    apdu, ConfigReportResponse(report.config_report_id).encode()))
            if apdu.event_type == nom.MDC_NOTI_SCAN_REPORT_FIXED.term and state.config:
                scan = ScanReportFixed.decode(apdu.event_info)
                self._emit(device, list(from_phd(phd.decode_scan(scan, state.config))))
                return phd.encode(phd.acknowledge(apdu))
            self._dead(f"phd:{device_id}", ValueError("event before a configuration"))
            return phd.encode(phd.Abort(0))
        if isinstance(apdu, ReleaseRequest):
            self._assoc.pop(device_id, None)
            return phd.encode(ReleaseResponse())
        return None

    def submit(self, kind: str, body: bytes, *, device_id: str,
               content_type: str | None = None) -> None:
        """A whole document from a device: `hl7v2`, `fhir`, `stow`, `vcf`, `photo`, `audio`,
        `video`, `usage`, `questionnaire_response` or `odk`.

        A walking video gives its gait features at `flush`; the video itself is not kept."""
        device = self.devices.get(device_id)
        if device is None:
            self._dead(f"{kind}:{device_id}", LookupError("unregistered device"))
            return
        try:
            if kind in ("hl7v2", "fhir"):
                self._uploads.append(_Upload(kind, body))
            elif kind == "stow":
                for part in stow_parts(body, content_type or ""):
                    self._uploads.append(_Upload("dicom", part))
            elif kind == "vcf":
                self._uploads.append(_Upload("vcf", body, device.hdt_id))
            elif kind == "photo":
                self._uploads.append(_Upload("media", body, device.hdt_id,
                                             content_type or "image/png"))
            elif kind == "audio":
                self._uploads.append(_Upload("media", body, device.hdt_id, "audio/wav"))
                self._emit(device, list(media.cough_rate(body, self.clock())))
            elif kind == "video":
                self._uploads.append(_Upload("video", body, device.hdt_id,
                                             content_type or "video/mp4", device_id))
            elif kind == "usage":
                self._emit(device, list(media.screen_time(body)))
            elif kind == "questionnaire_response":
                self._emit(device, [self_report.from_questionnaire_response(json.loads(body))])
            elif kind == "odk":
                self._emit(device, [self_report.from_odk(body, self.clock())])
            else:
                raise ValueError(f"unknown document kind {kind}")
        except (ValueError, KeyError) as exc:
            self._dead(f"{kind}:{device_id}", exc)

    def submit_wfdb(self, header: str, data: bytes, *, device_id: str) -> None:
        """A WFDB record replayed by an ECG machine. Lead II is the one twin field of the 12
        leads (`cardiovascular.ecg_lead_ii`); the other signals stay in the record."""
        try:
            device = self.devices[device_id]
            h = wfdb.parse_header(header)
            values = wfdb.read_format16(h, data)
            start = (h.start or self.clock()).replace(tzinfo=UTC)
            for i, s in enumerate(h.signals):
                if s.description.strip().upper() in LEAD_II_NAMES:
                    self._emit(device, [CodedReading(
                        streams.ECG_LEAD_II, {"array": [float(v) for v in values[:, i]],
                                              "period_ms": 1000.0 / h.fs}, s.units, start)])
        except (ValueError, KeyError) as exc:
            self._dead(f"wfdb:{device_id}", exc)

    async def _gait(self, upload: _Upload) -> None:
        device = self.devices[upload.device_id or ""]
        try:
            track = await asyncio.to_thread(self.pose_tracker, upload.body,
                                            upload.content_type or "")
            time = track.t0 or self.clock()
            self._emit(device, list(gait.features(track).readings(time)))
        except (ValueError, OSError) as exc:
            self._dead(f"video:{device.device_id}", exc)

    def _device_of(self, device_id: str) -> tuple[str, str] | None:
        d = self.devices.get(device_id)
        return (d.hdt_id, d.device_class) if d else None

    async def flush(self) -> FlushResult:
        result = FlushResult()
        if self.actuation is not None:
            result.actuations = await self.actuation.process(self._device_of)
        videos = [u for u in self._uploads if u.kind == "video"]
        self._uploads = [u for u in self._uploads if u.kind != "video"]
        for u in videos:
            await self._gait(u)
        groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for p in self._pending:
            p["source"] = "self_report" if p["code"]["code"] in SELF_REPORT_CODES else "device"
            twin = self.twin_of(Code.model_validate(p["code"])) or "unrouted"
            groups[(twin, p["hdt_id"])].append(p)
        self._pending = []
        now = self.clock()
        for (twin, hdt_id), observations in groups.items():
            await self.events.publish(EventEnvelope(
                event_id=new_record_id(), event_type=f"ingest.{twin}", source="edge",
                hdt_id=hdt_id, wall_time=now, trace_id=new_record_id(),
                payload={"observations": observations}))
            result.observations += len(observations)
        uploads, self._uploads = self._uploads, []
        for u in uploads:
            if u.kind in ("hl7v2", "fhir"):
                result.uploads.append(await self.sink.observations(u.kind, u.body))
            elif u.kind == "dicom":
                result.uploads.append(await self.sink.dicom(u.body))
            elif u.kind == "vcf" and u.hdt_id:
                result.uploads.append(await self.sink.vcf(u.body, hdt_id=u.hdt_id))
            elif u.hdt_id:
                result.uploads.append(await self.sink.media(
                    u.body, hdt_id=u.hdt_id, content_type=u.content_type or ""))
        return result

