"""Schema registration (p0 file registry, p1 Apicurio over a mocked HTTP transport) and the
p1 Kafka and MQTT transports over fake clients. No broker or registry is started."""

import asyncio
import json
import sys
from types import ModuleType

import httpx
import pytest

from ahdt.coupling.manager import build_coupling
from ahdt.coupling.registration import ContractDrift, expected_schemas, register_contracts
from ahdt.coupling.transport import SharedTransport
from atra.backends.apicurio import ApicurioSchemaRegistry
from atra.backends.memory import FileSchemaRegistry
from atra.config import ROOT
from atra.connectors import DTKind as K
from atra.connectors import KafkaTransport, MQTTTransport

from .cases import CASES
from .conftest import ALL_PURPOSES, HDT

CONNECTOR_SCHEMAS = ROOT / "contracts" / "schemas" / "connectors"
BASE = "http://apicurio.test/apis/registry/v3"


async def test_file_registry_holds_every_contract_unchanged():
    registry = FileSchemaRegistry(CONNECTOR_SCHEMAS)
    assert await register_contracts(registry) == []
    assert "2.0" in await registry.versions("renal_function")
    assert ("connector_envelope", "1.0") in expected_schemas()


async def test_registration_stops_on_drift():
    registry = FileSchemaRegistry(CONNECTOR_SCHEMAS)
    changed = dict(await registry.get("glycaemia", "1.0"), additionalProperties=True)
    await registry.register("glycaemia", "1.0", changed)
    with pytest.raises(ContractDrift, match=r"glycaemia v1\.0"):
        await register_contracts(registry)


class FakeApicurio:
    """The v3 artifact routes the client uses, over httpx.MockTransport."""

    def __init__(self):
        self.artifacts = {}
        self.requests = []

    def __call__(self, request):
        self.requests.append(request)
        path = request.url.path.removeprefix("/apis/registry/v3")
        parts = path.strip("/").split("/")
        if request.method == "POST" and parts[2:] == ["artifacts"]:
            body = json.loads(request.content)
            version = body["firstVersion"]
            self.artifacts.setdefault(body["artifactId"], {})[version["version"]] = (
                version["content"]["content"])
            return httpx.Response(200, json={"artifact": {"artifactId": body["artifactId"]}})
        versions = self.artifacts.get(parts[3]) if len(parts) > 3 else None
        if versions is None:
            return httpx.Response(404, json={"status": 404})
        if request.method == "GET" and parts[4:] == ["versions"]:
            return httpx.Response(200, json={"count": len(versions), "versions": [
                {"version": v} for v in versions]})
        if request.method == "GET" and len(parts) == 7 and parts[6] == "content":
            if parts[5] not in versions:
                return httpx.Response(404, json={"status": 404})
            return httpx.Response(200, content=versions[parts[5]],
                                  headers={"content-type": "application/json"})
        return httpx.Response(405)


async def test_apicurio_client_registers_and_reads_contracts():
    fake = FakeApicurio()
    client = httpx.AsyncClient(transport=httpx.MockTransport(fake))
    registry = ApicurioSchemaRegistry(BASE, client=client)
    added = await register_contracts(registry)
    assert len(added) == len(expected_schemas())
    post = next(r for r in fake.requests if r.method == "POST")
    assert post.url.path == "/apis/registry/v3/groups/atra.connectors/artifacts"
    assert post.url.params["ifExists"] == "FIND_OR_CREATE_VERSION"
    body = json.loads(post.content)
    assert body["artifactType"] == "JSON"
    assert body["firstVersion"]["content"]["contentType"] == "application/json"
    schema = await registry.get("renal_function", "2.0")
    assert schema["properties"]["egfr"]["x-ucum"] == "mL/min/{1.73_m2}"
    assert await registry.versions("renal_function") == ["2.0"]
    assert await registry.versions("unknown") == []
    with pytest.raises(KeyError):
        await registry.get("renal_function", "9.0")
    assert await register_contracts(registry) == []
    await registry.aclose()


def fake_aiokafka():
    """Producer and consumers share one in-process log per topic."""
    topics = {}
    module = ModuleType("aiokafka")

    class Producer:
        starts = 0

        def __init__(self, bootstrap_servers, **kw):
            self.kw = kw

        async def start(self):
            Producer.starts += 1

        async def stop(self):
            return None

        async def send_and_wait(self, topic, value):
            for queue in topics.get(topic, []):
                await queue.put(value)

    class Consumer:
        def __init__(self, topic, bootstrap_servers, group_id, **kw):
            self.queue = asyncio.Queue()
            topics.setdefault(topic, []).append(self.queue)

        async def start(self):
            return None

        async def stop(self):
            return None

        def __aiter__(self):
            return self

        async def __anext__(self):
            value = await self.queue.get()
            return type("Record", (), {"value": value})

    module.AIOKafkaProducer, module.AIOKafkaConsumer = Producer, Consumer
    return module, topics


def fake_aiomqtt_client(connections):
    class Message:
        def __init__(self, topic, payload):
            self.topic, self.payload = topic, payload

    class Client:
        def __init__(self, hostname, port=1883, **kw):
            self.subs, self.queue = set(), asyncio.Queue()
            connections.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return None

        async def subscribe(self, topic, qos=0):
            self.subs.add(topic)

        async def publish(self, topic, payload=None, qos=0):
            if topic in self.subs:
                await self.queue.put(Message(topic, payload))

        @property
        def messages(self):
            async def gen():
                while True:
                    yield await self.queue.get()
            return gen()

    return Client


async def _deliver_one(transport):
    from atra.consent import ConsentRegistry
    from atra.gateway import PatientConsent

    consents = ConsentRegistry({HDT: PatientConsent(set(ALL_PURPOSES), set())})
    coupling = build_coupling(HDT, SharedTransport(transport), consents=consents, window_s=0)
    await coupling.start()
    c = coupling.get("GlucoseRenalConnector", K.ENDOCRINE, K.RENAL_URINARY)
    await c.publish(CASES["GlucoseRenalConnector"].valid)
    for _ in range(50):
        if coupling.inbox.payloads(K.RENAL_URINARY):
            break
        await asyncio.sleep(0.01)
    await coupling.stop()
    await transport.close()
    return coupling.inbox.payloads(K.RENAL_URINARY)["GlucoseRenalConnector"]


async def test_kafka_transport_carries_connector_messages(monkeypatch):
    module, topics = fake_aiokafka()
    monkeypatch.setitem(sys.modules, "aiokafka", module)
    payload = await _deliver_one(KafkaTransport("kafka.test:9092", group_id="atra-ahdt"))
    assert payload == {"glucose": 7.8, "hba1c": 7.1}
    assert module.AIOKafkaProducer.starts == 1
    assert f"hdt.{HDT}.endocrine.to.renal_urinary.glycaemia.v1" in topics


async def test_mqtt_transport_carries_connector_messages(monkeypatch):
    import aiomqtt

    connections = []
    monkeypatch.setattr(aiomqtt, "Client", fake_aiomqtt_client(connections))
    payload = await _deliver_one(MQTTTransport("mqtt.test", 1883))
    assert payload == {"glucose": 7.8, "hba1c": 7.1}
    assert len(connections) == 1
    assert f"hdt/{HDT}/endocrine/to/renal_urinary/glycaemia/v1" in connections[0].subs
