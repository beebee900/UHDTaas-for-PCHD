"""Edge service (port 8095, CoAP 5683/udp): device registry and provisioning, link profile,
outbox status, local alerts and the edge assistant (design 04, 4.2)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal

from cryptography.x509 import load_pem_x509_csr
from fastapi import FastAPI, Path, Query, Request
from pydantic import BaseModel, Field

from atra.backends import Backends
from atra.config import Settings, get_settings
from atra.consent import ConsentRegistry, demo_registry
from atra.policy import PolicyClient
from atra.security import client_ssl_context
from atra.service import Problem, authenticate, create_app, verifier_of
from edge.actuators.service import ActuationService, MqttEndpoint
from edge.alerts import AlertDispatcher
from edge.config import EdgeSettings, LinkProfile
from edge.devices.transport import Transports
from edge.inference import OnnxHost
from edge.ingress import MqttIngress, coap_server, mqtt_client
from edge.outbox import Outbox
from edge.registry import DeviceCA, DeviceClass, DeviceRecord, DeviceRegistry, RegistryError
from edge.runtime import EdgeRuntime
from edge.slm import EdgeAssistant, LlamaCppSLM, OfflineSLM
from edge.uplink import GrpcIngestor, credentials

log = logging.getLogger(__name__)
OPERATOR_ROLES = frozenset({"administrator", "community_health_worker", "nurse", "person"})
SERVICE_CLIENT = "edge-svc"


class DeviceRegistration(BaseModel):
    device_id: Annotated[str, Field(pattern=r"^[a-z0-9-]{3,64}$")]
    device_class: DeviceClass
    hdt_id: Annotated[str, Field(pattern=r"^hdt-[0-9a-f]{12}$")]
    model: str | None = None
    firmware_version: str | None = None


class Device(DeviceRegistration):
    registered_at: datetime
    provisioned: bool = False
    provisioned_at: datetime | None = None
    attested_at: datetime | None = None
    cert_fingerprint: str | None = None
    topic: str


class ProvisionRequest(BaseModel):
    csr_pem: Annotated[str, Field(description="PKCS#10 certificate signing request, PEM")]
    firmware_version: str | None = None


class Provisioned(BaseModel):
    device: Device
    certificate_pem: str
    ca_pem: str


class LinkChange(BaseModel):
    profile: LinkProfile


class OutboxStatus(BaseModel):
    pending: int
    acked: int = 0
    rejected: int = 0
    oldest: datetime | None = None
    profile: LinkProfile = "wifi"
    link: Literal["up", "down"]


class EdgeAlert(BaseModel):
    alert_id: str
    hdt_id: str
    source: Literal["rule", "model"]
    rule: str
    urgency: Literal["emergency", "urgent", "routine"]
    time: datetime
    field: str | None = None
    value: float | None = None
    unit: str | None = None
    probability: float | None = None
    notified: str | None = None
    sms: str | None = None


class Summary(BaseModel):
    hdt_id: str
    day: date
    text: str


def _device(r: DeviceRecord) -> Device:
    return Device(device_id=r.device_id, device_class=r.device_class,
                  hdt_id=r.hdt_id, model=r.model, firmware_version=r.firmware_version,
                  registered_at=r.registered_at, provisioned=r.provisioned_at is not None,
                  provisioned_at=r.provisioned_at, attested_at=r.attested_at,
                  cert_fingerprint=r.cert_fingerprint, topic=r.topic)


def _ca(settings: Settings) -> DeviceCA:
    pki = settings.security.pki_dir
    if (pki / "ca.key").is_file() and (pki / "ca.crt").is_file():
        return DeviceCA.from_dir(pki)
    return DeviceCA.generate()


def build_runtime(settings: Settings, edge: EdgeSettings, backends: Backends, audit: Any, *,
                  consents: ConsentRegistry) -> EdgeRuntime:
    persistent = not backends.ephemeral
    transports = Transports()
    actuation = ActuationService(PolicyClient(settings.infra.opa), audit, backends.workflows,
                                 mqtt=MqttEndpoint(transports.mqtt.publish),
                                 consent_of=consents.get)
    pki = settings.security.pki_dir
    tls = credentials(pki) if settings.security.mtls else None
    issuer = backends.issuer
    ingestor = GrpcIngestor(edge.ahdt_grpc, lambda: issuer.issue_service(SERVICE_CLIENT),
                            tls=tls, timeout_s=edge.ingest_timeout_s)
    return EdgeRuntime(
        edge,
        registry=DeviceRegistry(edge.path("devices.sqlite") if persistent else None,
                                _ca(settings)),
        outbox=Outbox(edge.path("outbox.sqlite") if persistent else None),
        ingestor=ingestor, models=OnnxHost.from_dir(edge.models_dir), actuation=actuation,
        dispatcher=AlertDispatcher(actuation,
                                   edge.path("alerts.sqlite") if persistent else None),
        transports=transports)


def build_app(settings: Settings | None = None, *, backends: Backends | None = None,
              edge: EdgeSettings | None = None, runtime: EdgeRuntime | None = None,
              step_s: float | None = 5.0) -> FastAPI:
    settings = settings or get_settings()
    edge = edge or EdgeSettings()
    tasks: list[asyncio.Task[Any]] = []

    async def loop(rt: EdgeRuntime, every_s: float) -> None:
        while True:
            try:
                await rt.step()
            except Exception:
                log.exception("edge step failed")
            await asyncio.sleep(every_s)

    async def startup(app: FastAPI) -> None:
        rt: EdgeRuntime = app.state.edge
        if step_s:
            tasks.append(asyncio.create_task(loop(rt, step_s)))
        if settings.profile != "p0":
            pki = settings.security.pki_dir
            tls = client_ssl_context(pki / "edge.crt", pki / "edge.key", pki / "ca.crt") \
                if edge.mqtt_tls else None
            ingress = MqttIngress(rt.transports.mqtt)
            tasks.append(asyncio.create_task(ingress.serve(
                lambda: mqtt_client(edge.mqtt_host, edge.mqtt_port, identifier=edge.site,
                                    tls=tls), retry_s=edge.retry_s)))
            app.state.coap = await coap_server(rt.transports.coap, "0.0.0.0", edge.coap_port)

    async def shutdown(app: FastAPI) -> None:
        for task in tasks:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if getattr(app.state, "coap", None) is not None:
            await app.state.coap.shutdown()
        rt: EdgeRuntime = app.state.edge
        rt.outbox.enqueue(rt.shaper.flush())
        if isinstance(rt.ingestor, GrpcIngestor):
            await rt.ingestor.close()

    app = create_app("edge", settings, backends=backends, title=f"Edge {edge.site}",
                     description="Edge tier: device registry, buffering and edge inference",
                     on_startup=startup, on_shutdown=shutdown)
    consents = demo_registry()
    rt = runtime or build_runtime(settings, edge, app.state.backends, app.state.audit,
                                  consents=consents)
    app.state.edge = rt
    slm = (LlamaCppSLM(settings.llm.edge_model_path) if edge.slm == "llama_cpp"
           else OfflineSLM())
    assistant = EdgeAssistant(slm)

    async def require_operator(request: Request) -> None:
        ident = await authenticate(dict(request.headers), await verifier_of(app))
        if not ident.delegated and ident.ctx.actor_role.value not in OPERATOR_ROLES:
            raise Problem(403, "forbidden", "this role may not manage devices")

    @app.post("/v1/devices", response_model=Device, status_code=201, tags=["devices"])
    async def register(request: Request, body: DeviceRegistration) -> Device:
        await require_operator(request)
        try:
            record = rt.registry.register(body.device_id, body.device_class, body.hdt_id,
                                          model=body.model,
                                          firmware_version=body.firmware_version)
        except FileExistsError as exc:
            raise Problem(409, "conflict", str(exc)) from exc
        return _device(record)

    @app.get("/v1/devices", response_model=list[Device], tags=["devices"])
    async def list_devices(request: Request) -> list[Device]:
        await require_operator(request)
        return [_device(r) for r in rt.registry.all()]

    @app.post("/v1/devices/{device_id}/provision", response_model=Provisioned,
              tags=["devices"])
    async def provision(request: Request, device_id: Annotated[str, Path()],
                        body: ProvisionRequest) -> Provisioned:
        await require_operator(request)
        try:
            load_pem_x509_csr(body.csr_pem.encode())
        except ValueError as exc:
            raise Problem(422, "invalid-csr", "csr_pem is not a PEM certificate request") \
                from exc
        try:
            record, cert = rt.registry.provision(device_id, body.csr_pem.encode(),
                                                 firmware_version=body.firmware_version)
        except RegistryError as exc:
            raise Problem(404, "not-found", str(exc)) from exc
        except ValueError as exc:
            raise Problem(422, "invalid-csr", str(exc)) from exc
        return Provisioned(device=_device(record), certificate_pem=cert,
                           ca_pem=rt.registry.ca.cert_pem)

    @app.get("/v1/outbox", response_model=OutboxStatus, tags=["outbox"])
    async def outbox() -> OutboxStatus:
        s = rt.status()
        return OutboxStatus(pending=s["pending"], acked=s["acked"], rejected=s["rejected"],
                            oldest=s["oldest"], profile=s["link"],
                            link="up" if s["cloud_reachable"] else "down")

    @app.put("/v1/link", response_model=OutboxStatus, tags=["outbox"])
    async def set_link(request: Request, body: LinkChange) -> OutboxStatus:
        await require_operator(request)
        rt.set_link(body.profile)
        return await outbox()

    @app.get("/v1/alerts", response_model=list[EdgeAlert], tags=["alerts"])
    async def alerts(request: Request,
                     limit: Annotated[int, Query(ge=1, le=500)] = 50) -> list[EdgeAlert]:
        await require_operator(request)
        if rt.dispatcher is None:
            return []
        return [EdgeAlert.model_validate(a) for a in rt.dispatcher.recent(limit)]

    @app.get("/v1/persons/{hdt_id}/summary", response_model=Summary, tags=["assistant"])
    async def summary(request: Request,
                      hdt_id: Annotated[str, Path(pattern=r"^hdt-[0-9a-f]{12}$")],
                      day: date | None = None) -> Summary:
        await require_operator(request)
        day = day or datetime.now(UTC).date()
        windows = [w for w in rt.history(hdt_id) if w.start.date() == day]
        text = await asyncio.to_thread(assistant.daily_summary, hdt_id, day, windows)
        return Summary(hdt_id=hdt_id, day=day, text=text)

    return app
