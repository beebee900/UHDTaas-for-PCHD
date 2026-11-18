"""Network ingress of the edge (design 04, 4.2.1 tier 3): MQTT over TLS, CoAP over UDP, and
LoRaWAN through the ChirpStack MQTT integration.

Both bridges hand the received frames to the in-process transports of `edge.devices`, so the
WP10 decoders and the `DeviceGateway` read the same bytes on the network as in p0.

- MQTT: an aiomqtt client subscribes, with QoS 1 and a persistent session, to the device
  topics `dev/+/+/+`, the ChirpStack uplink topic `application/+/device/+/event/up` and the
  agents' actuator topics `act/+/+/+`. Each
  message is re-framed as an MQTT 3.1.1 PUBLISH for the in-process broker. Commands that the
  gateway publishes on `cmd/#` go back out to the network broker.
- CoAP: an aiocoap server takes every request and passes it, as an RFC 7252 datagram, to the
  `CoapEndpoint` that the gateway's environmental resources are on.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import ssl
from collections.abc import AsyncIterator, Callable
from typing import Any, Protocol

import aiocoap
from aiocoap import resource
from aiocoap.numbers.codes import Code as CoapCode

from edge.actuators.catalogue import ACT_TOPIC
from edge.devices.decode import environment
from edge.devices.gateway import DEVICE_TOPIC
from edge.devices.transport import coap as coap_codec
from edge.devices.transport.coap import CoapEndpoint
from edge.devices.transport.mqtt import MqttBroker, Publish, encode_publish

log = logging.getLogger(__name__)

INGRESS_TOPICS = (DEVICE_TOPIC, environment.UPLINK_TOPIC, ACT_TOPIC)
COMMAND_TOPIC = "cmd/#"


class MqttClient(Protocol):
    """The part of `aiomqtt.Client` the bridge uses."""

    async def subscribe(self, topic: str, qos: int = 0) -> Any: ...

    async def publish(self, topic: str, payload: bytes | None = None, qos: int = 0) -> None: ...

    @property
    def messages(self) -> AsyncIterator[Any]: ...


def mqtt_client(host: str, port: int, *, identifier: str,
                tls: ssl.SSLContext | None) -> Any:
    """An aiomqtt client with a persistent session, so the broker keeps QoS 1 messages for
    the edge while it is disconnected."""
    import aiomqtt

    return aiomqtt.Client(host, port, identifier=identifier, clean_session=False,
                          tls_context=tls)


class MqttIngress:
    def __init__(self, broker: MqttBroker) -> None:
        self.broker = broker
        self.received = 0
        self._commands: asyncio.Queue[Publish] = asyncio.Queue()
        broker.subscribe(COMMAND_TOPIC, self._commands.put_nowait)

    def deliver(self, topic: str, payload: bytes, qos: int = 0) -> None:
        self.broker.publish(encode_publish(Publish(topic, payload, qos=min(qos, 1),
                                                   packet_id=1 if qos else None)))
        self.received += 1

    async def _downlink(self, client: MqttClient) -> None:
        while True:
            command = await self._commands.get()
            await client.publish(command.topic, command.payload, qos=command.qos)

    async def run(self, client: MqttClient) -> None:
        """Bridge one connected client until its message stream ends."""
        for topic in INGRESS_TOPICS:
            await client.subscribe(topic, qos=1)
        downlink = asyncio.create_task(self._downlink(client))
        try:
            async for message in client.messages:
                self.deliver(message.topic.value, bytes(message.payload), message.qos)
        finally:
            downlink.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await downlink

    async def serve(self, connect: Callable[[], Any], *, retry_s: float = 5.0) -> None:
        """Connect, bridge, and reconnect after every broker error."""
        import aiomqtt

        while True:
            try:
                async with connect() as client:
                    await self.run(client)
            except aiomqtt.MqttError as exc:
                log.warning("MQTT broker unavailable: %s", exc)
            await asyncio.sleep(retry_s)


def _code_of(reply: bytes | None) -> int:
    return coap_codec.decode(reply).code if reply else coap_codec.CHANGED


class CoapBridge(resource.Resource):  # type: ignore[misc]
    """An aiocoap site that answers every request through the in-process endpoint."""

    def __init__(self, endpoint: CoapEndpoint) -> None:
        super().__init__()
        self.endpoint = endpoint
        self._mid = 0

    async def render(self, request: Any) -> Any:
        self._mid = (self._mid + 1) % 0x10000
        options = coap_codec.path_options("/".join(request.opt.uri_path))
        if request.opt.content_format is not None:
            options += ((coap_codec.CONTENT_FORMAT,
                         coap_codec.uint_option(int(request.opt.content_format))),)
        datagram = coap_codec.encode(coap_codec.Message(
            coap_codec.CON, int(request.code), self._mid, b"", options, bytes(request.payload)))
        try:
            code = _code_of(self.endpoint.send(datagram))
        except coap_codec.CoapError:
            code = int(CoapCode.BAD_REQUEST)
        return aiocoap.Message(code=CoapCode(code))


async def coap_server(endpoint: CoapEndpoint, host: str, port: int) -> Any:
    """Start the CoAP server; `shutdown()` the returned context to stop it."""
    return await aiocoap.Context.create_server_context(CoapBridge(endpoint), bind=(host, port))
