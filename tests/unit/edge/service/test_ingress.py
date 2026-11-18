"""MQTT ingress through an aiomqtt-shaped client and CoAP over localhost UDP (design 04,
4.2.1 tier 3)."""

import asyncio
import json
import socket

import aiocoap
import aiomqtt
from aiocoap.numbers.codes import Code

from edge.devices.transport.coap import APPLICATION_JSON
from edge.devices.transport.mqtt import Publish, encode_publish
from edge.ingress import COMMAND_TOPIC, INGRESS_TOPICS, MqttIngress, coap_server
from edge.outbox import Outbox
from edge.registry import DeviceCA, DeviceRegistry
from edge.runtime import EdgeRuntime
from tests.unit.edge.service.support import HDT, START


class FakeClient:
    """The subscribe, publish and messages surface of `aiomqtt.Client`."""

    def __init__(self, messages):
        self._messages = messages
        self.subscriptions = []
        self.published = []
        self.ended = asyncio.Event()

    async def subscribe(self, topic, qos=0):
        self.subscriptions.append((topic, qos))

    async def publish(self, topic, payload=None, qos=0):
        self.published.append((topic, payload, qos))

    @property
    def messages(self):
        return self._iterate()

    async def _iterate(self):
        for m in self._messages:
            yield m
            await asyncio.sleep(0)
        await self.ended.wait()


class Offline:
    async def ingest(self, observations):
        raise AssertionError("not called in these tests")


def runtime(edge_settings):
    rt = EdgeRuntime(edge_settings.model_copy(update={"link": "offline"}),
                     registry=DeviceRegistry(None, DeviceCA.generate()),
                     outbox=Outbox(None), ingestor=Offline(), clock=lambda: START)
    return rt


async def test_mqtt_bridge_subscribes_relays_frames_and_returns_commands(edge_settings):
    rt = runtime(edge_settings)
    rt.registry.register("po-1", "pulse_oximeter", HDT)
    body = json.dumps({"time": START.isoformat(), "spo2_pct": 97, "pulse_rate": 71}).encode()
    messages = [aiomqtt.Message(f"dev/{HDT}/po-1/pulse_oximeter", body, 1, False, 7, None),
                aiomqtt.Message(f"dev/{HDT}/ghost/pulse_oximeter", body, 1, False, 8, None)]
    client = FakeClient(messages)
    ingress = MqttIngress(rt.transports.mqtt)
    task = asyncio.create_task(ingress.run(client))
    for _ in range(100):
        if ingress.received == 2:
            break
        await asyncio.sleep(0)

    rt.transports.mqtt.publish(encode_publish(Publish(f"cmd/{HDT}/lamp-1/lighting", b"{}",
                                                      qos=1, packet_id=3)))
    for _ in range(100):
        if client.published:
            break
        await asyncio.sleep(0)
    client.ended.set()
    task.cancel()

    assert client.subscriptions == [(t, 1) for t in INGRESS_TOPICS]
    assert COMMAND_TOPIC == "cmd/#"
    assert client.published == [(f"cmd/{HDT}/lamp-1/lighting", b"{}", 1)]
    result = await rt.step()
    values = sorted((p["code"]["code"], p["value"]) for p in rt.outbox.pending(10)
                    for p in [p.payload])
    assert result.readings == 2 and values == [("59408-5", 97), ("8867-4", 71)]
    assert [topic for topic, _ in rt.gateway.dead_letters] == [
        f"dev/{HDT}/ghost/pulse_oximeter"]


def free_udp_port():
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def test_coap_post_over_localhost_udp_reaches_the_gateway(edge_settings):
    rt = runtime(edge_settings)
    rt.registry.register("air-1", "environmental", HDT)
    port = free_udp_port()
    server = await coap_server(rt.transports.coap, "127.0.0.1", port)
    client = await aiocoap.Context.create_client_context()
    try:
        body = json.dumps({"time": START.isoformat(), "pm25_ugm3": 31.5,
                           "temperature_c": 29.0, "humidity_pct": 71.0}).encode()
        request = aiocoap.Message(code=Code.POST, uri=f"coap://127.0.0.1:{port}/env/air-1",
                                  payload=body, content_format=APPLICATION_JSON)
        reply = await asyncio.wait_for(client.request(request).response, 10)
        missing = aiocoap.Message(code=Code.POST, uri=f"coap://127.0.0.1:{port}/env/none",
                                  payload=body, content_format=APPLICATION_JSON)
        not_found = await asyncio.wait_for(client.request(missing).response, 10)
    finally:
        await client.shutdown()
        await server.shutdown()
    assert reply.code == Code.CHANGED
    assert not_found.code == Code.NOT_FOUND
    result = await rt.step()
    assert result.readings == 3
    assert {p.payload["device_id"] for p in rt.outbox.pending(10)} == {"air-1"}
