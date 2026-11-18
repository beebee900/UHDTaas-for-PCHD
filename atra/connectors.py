"""
atra.connectors
===============

Layer 6.5 (Connection Services) of the Agentic Twin Reference Architecture (ATRA)
for the Agentic Human Digital Twin (AHDT) and the Agentic Patient Digital Twin (APDT).

Revised Layer 6 order: 6.1 Data, 6.2 AI/ML/Simulation, 6.3 XAI, 6.4 Cognitive,
6.5 Connection.

A Connector is the only sanctioned path for data to move from one digital twin
(DT) to another. It binds:

    source DT  --(map -> validate -> authorise -> stamp provenance -> send)-->  target DT

and, for bidirectional connectors, the reverse path as well.

Contents
--------
DTKind              The 17 DTs of the Human Digital Twin.
TwinEndpoint        Identity of one DT instance belonging to one person's HDT.
FieldSpec,
DataContract        Versioned schema for an inter-DT exchange (units, ranges).
Message             The envelope moved by a Connector (payload + provenance).
Transport           Abstract transport; InMemoryTransport, MQTTTransport, KafkaTransport.
Policy              Abstract policy; ConsentPolicy, RangeGuardPolicy.
QoS                 Retry, back-off, timeout and buffering settings.
Connector           Abstract base class to specialise for each DT pair.
ConnectorManager    Registry of connectors + the coupling matrix for one HDT.

Example specialisations
-----------------------
CardiovascularRespiratoryConnector   bidirectional, stream  (O2 delivery <-> gas exchange)
EndocrineBehaviouralConnector        bidirectional, push    (glucose/cortisol <-> activity/sleep)
IndividualToPopulationConnector      unidirectional, push   (de-identified contribution)

Only the Python standard library is required. MQTT and Kafka transports import
their client libraries lazily (aiomqtt, aiokafka) so the module runs without them.

Run the demo:   python -m atra.connectors
Run the tests:  python -m pytest tests/unit/atra/test_connectors.py -q
"""

from __future__ import annotations

import abc
import asyncio
import dataclasses
import enum
import hashlib
import json
import logging
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Deque, Dict, List, Mapping, Optional, Tuple

log = logging.getLogger("atra.connectors")

__all__ = [
    "DTKind", "TwinEndpoint", "FieldSpec", "DataContract", "ContractViolation",
    "Message", "Transport", "InMemoryTransport", "MQTTTransport", "KafkaTransport",
    "Decision", "Policy", "ConsentPolicy", "RangeGuardPolicy", "PolicyDenied",
    "SyncMode", "Direction", "QoS", "ConnectorState", "Connector", "ConnectorManager",
    "CardiovascularRespiratoryConnector", "EndocrineBehaviouralConnector",
    "IndividualToPopulationConnector",
]


# ---------------------------------------------------------------------------
# 1. The 17 digital twins of the Human Digital Twin
# ---------------------------------------------------------------------------

class DTKind(str, enum.Enum):
    """The 17 peer DTs of the federated Human Digital Twin, plus the Patient DT (APDT)."""
    # 13 Physiological System DTs
    CARDIOVASCULAR = "cardiovascular"
    RESPIRATORY = "respiratory"
    NERVOUS = "nervous"
    SENSORY = "sensory"
    DIGESTIVE = "digestive"
    HEPATOBILIARY = "hepatobiliary"
    RENAL_URINARY = "renal_urinary"
    ENDOCRINE = "endocrine"
    IMMUNE_LYMPHATIC = "immune_lymphatic"
    HAEMATOLOGICAL = "haematological"
    MUSCULOSKELETAL = "musculoskeletal"
    INTEGUMENTARY = "integumentary"
    REPRODUCTIVE = "reproductive"
    # 4 integrative DTs
    WHOLE_BODY = "whole_body"
    BEHAVIOURAL_COGNITIVE = "behavioural_cognitive"
    SOCIAL = "social"
    POPULATION = "population"
    # Separate agentic twin that uses the AHDT (not one of the 17)
    PATIENT = "patient"

    @property
    def is_physiological(self) -> bool:
        return self not in {DTKind.WHOLE_BODY, DTKind.BEHAVIOURAL_COGNITIVE,
                            DTKind.SOCIAL, DTKind.POPULATION, DTKind.PATIENT}

    @property
    def is_ahdt_member(self) -> bool:
        """True for the 17 DTs of the Human Digital Twin; False for the APDT."""
        return self is not DTKind.PATIENT


@dataclass(frozen=True)
class TwinEndpoint:
    """Identity of one DT inside one person's HDT.

    hdt_id is a pseudonymous identifier; no direct identifiers travel in messages.
    For the Population DT, hdt_id names the cohort or platform-level twin.
    """
    hdt_id: str
    kind: DTKind
    instance: str = "primary"

    @property
    def uri(self) -> str:
        return f"hdt://{self.hdt_id}/{self.kind.value}/{self.instance}"


# ---------------------------------------------------------------------------
# 2. Data contracts
# ---------------------------------------------------------------------------

class ContractViolation(ValueError):
    """Raised when a payload does not satisfy its DataContract."""

    def __init__(self, contract: str, errors: List[str]):
        super().__init__(f"{contract}: " + "; ".join(errors))
        self.errors = errors


_PY_TYPES: Dict[str, Tuple[type, ...]] = {
    "float": (int, float), "int": (int,), "str": (str,), "bool": (bool,),
    "list": (list, tuple), "dict": (dict,),
}


@dataclass(frozen=True)
class FieldSpec:
    """One variable in an inter-DT exchange, with its unit and plausible range."""
    dtype: str = "float"
    unit: Optional[str] = None           # UCUM unit string, e.g. "mm[Hg]", "L/min", "mmol/L"
    required: bool = True
    min: Optional[float] = None
    max: Optional[float] = None
    description: str = ""

    def check(self, name: str, value: Any) -> List[str]:
        errs: List[str] = []
        types = _PY_TYPES.get(self.dtype, (object,))
        if isinstance(value, bool) and self.dtype in ("float", "int"):
            return [f"{name}: expected {self.dtype}, got bool"]
        if not isinstance(value, types):
            return [f"{name}: expected {self.dtype}, got {type(value).__name__}"]
        if self.dtype in ("float", "int"):
            if self.min is not None and value < self.min:
                errs.append(f"{name}={value} below min {self.min} {self.unit or ''}".rstrip())
            if self.max is not None and value > self.max:
                errs.append(f"{name}={value} above max {self.max} {self.unit or ''}".rstrip())
        return errs


@dataclass(frozen=True)
class DataContract:
    """Versioned schema for one direction of an inter-DT exchange.

    In production, contracts live in a schema registry (Confluent, Apicurio) as
    Avro, Protobuf or JSON Schema; this class is the in-process equivalent.
    """
    name: str
    version: str
    fields: Mapping[str, FieldSpec]
    allow_extra: bool = False

    @property
    def major(self) -> int:
        return int(self.version.split(".")[0])

    def validate(self, payload: Mapping[str, Any]) -> None:
        errors: List[str] = []
        for fname, spec in self.fields.items():
            if fname not in payload or payload[fname] is None:
                if spec.required:
                    errors.append(f"{fname}: missing")
                continue
            errors.extend(spec.check(fname, payload[fname]))
        if not self.allow_extra:
            extra = set(payload) - set(self.fields)
            if extra:
                errors.append(f"unexpected fields: {sorted(extra)}")
        if errors:
            raise ContractViolation(f"{self.name} v{self.version}", errors)

    def units(self) -> Dict[str, Optional[str]]:
        return {k: v.unit for k, v in self.fields.items()}


# ---------------------------------------------------------------------------
# 3. Message envelope
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """Envelope moved between DTs. Provenance feeds Layer 5 cross-model explanations."""
    source: str                      # TwinEndpoint.uri
    target: str                      # TwinEndpoint.uri
    contract: str                    # "<name>/v<version>"
    payload: Dict[str, Any]
    units: Dict[str, Optional[str]]
    sim_time: Optional[float] = None         # model/simulation time (s), for co-simulation ordering
    wall_time: float = field(default_factory=time.time)
    msg_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    trace_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    correlation_id: Optional[str] = None     # set on request-reply
    reply_to: Optional[str] = None           # topic for request-reply
    purpose: str = "care"                    # purpose of use, checked by ConsentPolicy
    provenance: Dict[str, Any] = field(default_factory=dict)
    seq: int = 0                             # per-connector sequence number

    def content_hash(self) -> str:
        body = json.dumps({"payload": self.payload, "contract": self.contract,
                           "source": self.source, "sim_time": self.sim_time},
                          sort_keys=True, default=str)
        return hashlib.sha256(body.encode()).hexdigest()

    def to_bytes(self) -> bytes:
        return json.dumps(dataclasses.asdict(self), default=str).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "Message":
        return cls(**json.loads(raw.decode()))


# ---------------------------------------------------------------------------
# 4. Transports
# ---------------------------------------------------------------------------

Handler = Callable[[bytes], Awaitable[None]]


class Transport(abc.ABC):
    """Abstract byte transport. Topic naming is decided by the Connector."""

    @abc.abstractmethod
    async def connect(self) -> None: ...

    @abc.abstractmethod
    async def publish(self, topic: str, data: bytes) -> None: ...

    @abc.abstractmethod
    async def subscribe(self, topic: str, handler: Handler) -> None: ...

    @abc.abstractmethod
    async def close(self) -> None: ...


class InMemoryTransport(Transport):
    """Process-local bus for tests, simulation runs and single-node edge deployments.

    fail_next can be set to simulate transient network failures.
    """

    def __init__(self) -> None:
        self._subs: Dict[str, List[Handler]] = defaultdict(list)
        self.published: List[Tuple[str, bytes]] = []
        self.fail_next = 0

    async def connect(self) -> None:
        return None

    async def publish(self, topic: str, data: bytes) -> None:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("simulated transport failure")
        self.published.append((topic, data))
        for handler in list(self._subs.get(topic, [])):
            await handler(data)

    async def subscribe(self, topic: str, handler: Handler) -> None:
        self._subs[topic].append(handler)

    async def close(self) -> None:
        self._subs.clear()


class MQTTTransport(Transport):
    """MQTT 5 transport (Mosquitto, EMQX, HiveMQ) using aiomqtt. QoS 1 by default."""

    def __init__(self, host: str, port: int = 8883, qos: int = 1, **client_kwargs: Any):
        self.host, self.port, self.qos, self.kw = host, port, qos, client_kwargs
        self._client: Any = None
        self._handlers: Dict[str, Handler] = {}
        self._task: Optional[asyncio.Task] = None

    async def connect(self) -> None:
        import aiomqtt  # lazy import: pip install aiomqtt
        self._client = aiomqtt.Client(self.host, self.port, **self.kw)
        await self._client.__aenter__()
        self._task = asyncio.create_task(self._pump())

    async def _pump(self) -> None:
        async for msg in self._client.messages:
            handler = self._handlers.get(str(msg.topic))
            if handler:
                await handler(bytes(msg.payload))

    async def publish(self, topic: str, data: bytes) -> None:
        await self._client.publish(topic, data, qos=self.qos)

    async def subscribe(self, topic: str, handler: Handler) -> None:
        self._handlers[topic] = handler
        await self._client.subscribe(topic, qos=self.qos)

    async def close(self) -> None:
        if self._task:
            self._task.cancel()
        if self._client:
            await self._client.__aexit__(None, None, None)


class KafkaTransport(Transport):
    """Kafka transport using aiokafka. MQTT topic separators are mapped to dots."""

    def __init__(self, bootstrap_servers: str, group_id: str = "atra-connectors", **kw: Any):
        self.bootstrap, self.group_id, self.kw = bootstrap_servers, group_id, kw
        self._producer: Any = None
        self._consumers: List[Any] = []
        self._tasks: List[asyncio.Task] = []

    @staticmethod
    def _t(topic: str) -> str:
        return topic.replace("/", ".")

    async def connect(self) -> None:
        from aiokafka import AIOKafkaProducer  # lazy import: pip install aiokafka
        self._producer = AIOKafkaProducer(bootstrap_servers=self.bootstrap, acks="all",
                                          enable_idempotence=True, **self.kw)
        await self._producer.start()

    async def publish(self, topic: str, data: bytes) -> None:
        await self._producer.send_and_wait(self._t(topic), data)

    async def subscribe(self, topic: str, handler: Handler) -> None:
        from aiokafka import AIOKafkaConsumer
        consumer = AIOKafkaConsumer(self._t(topic), bootstrap_servers=self.bootstrap,
                                    group_id=self.group_id, **self.kw)
        await consumer.start()
        self._consumers.append(consumer)

        async def pump() -> None:
            async for rec in consumer:
                await handler(rec.value)

        self._tasks.append(asyncio.create_task(pump()))

    async def close(self) -> None:
        for t in self._tasks:
            t.cancel()
        for c in self._consumers:
            await c.stop()
        if self._producer:
            await self._producer.stop()


# ---------------------------------------------------------------------------
# 5. Policies (consent, safety). In production, delegate to Open Policy Agent.
# ---------------------------------------------------------------------------

class PolicyDenied(PermissionError):
    pass


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = ""
    policy: str = ""


class Policy(abc.ABC):
    """A check applied to every message in a given direction ('out' or 'in')."""

    name: str = "policy"

    @abc.abstractmethod
    def evaluate(self, message: Message, direction: str) -> Decision: ...


class ConsentPolicy(Policy):
    """Allows a message only for purposes the person has consented to for this DT pair.

    consents maps (source_kind, target_kind) -> set of permitted purposes.
    """

    name = "consent"

    def __init__(self, consents: Mapping[Tuple[DTKind, DTKind], set]):
        self.consents = {(a.value, b.value): set(p) for (a, b), p in consents.items()}

    def evaluate(self, message: Message, direction: str) -> Decision:
        src = message.source.split("/")[3]
        tgt = message.target.split("/")[3]
        permitted = self.consents.get((src, tgt), set())
        if message.purpose in permitted:
            return Decision(True, policy=self.name)
        return Decision(False, f"no consent for purpose '{message.purpose}' {src}->{tgt}", self.name)


class RangeGuardPolicy(Policy):
    """Safety guard: blocks physiologically impossible values that passed schema typing.

    limits maps field name -> (min, max). Complements DataContract ranges when a
    stricter clinical guard is required on a specific connector.
    """

    name = "range_guard"

    def __init__(self, limits: Mapping[str, Tuple[float, float]]):
        self.limits = dict(limits)

    def evaluate(self, message: Message, direction: str) -> Decision:
        for k, (lo, hi) in self.limits.items():
            v = message.payload.get(k)
            if isinstance(v, (int, float)) and not (lo <= v <= hi):
                return Decision(False, f"{k}={v} outside safety range [{lo}, {hi}]", self.name)
        return Decision(True, policy=self.name)


# ---------------------------------------------------------------------------
# 6. Connector
# ---------------------------------------------------------------------------

class SyncMode(str, enum.Enum):
    PUSH = "push"                    # source sends on change
    PULL = "pull"                    # target requests when it needs data
    STREAM = "stream"                # continuous, rate-limited flow
    REQUEST_REPLY = "request_reply"  # query with correlated answer


class Direction(str, enum.Enum):
    UNIDIRECTIONAL = "unidirectional"
    BIDIRECTIONAL = "bidirectional"


class ConnectorState(str, enum.Enum):
    CREATED = "created"
    RUNNING = "running"
    DEGRADED = "degraded"            # delivering from buffer / retrying
    STOPPED = "stopped"


@dataclass
class QoS:
    max_retries: int = 3
    backoff_s: float = 0.05          # doubled on each retry
    request_timeout_s: float = 5.0
    buffer_size: int = 1000          # store-and-forward capacity when transport is down
    min_interval_s: float = 0.0      # rate limit for STREAM mode


DeliverFn = Callable[[Message], Awaitable[None]]
StateFn = Callable[[], Awaitable[Dict[str, Any]]]


class Connector(abc.ABC):
    """Abstract inter-DT connector at ATRA Layer 6.5.

    Subclasses specialise a connector for one DT pair by:
      * declaring SOURCE_KIND and TARGET_KIND (checked at construction),
      * declaring OUT_CONTRACT (and IN_CONTRACT for bidirectional connectors),
      * implementing map_outbound(): source-DT state -> OUT_CONTRACT payload,
      * optionally implementing map_inbound(): IN_CONTRACT payload -> source-DT update.

    The base class supplies the pipeline:
      map -> validate -> authorise -> stamp provenance -> serialise -> send (retry, buffer)
      receive -> deserialise -> validate -> authorise -> de-duplicate -> deliver
    plus request-reply, rate limiting, metrics and health.

    Wiring to the rest of ATRA:
      * on_deliver_to_target: the target DT's ingestion hook (Layer 6.1 data service
        or the target orchestrator agent at Layer 7.2);
      * on_deliver_to_source: the source DT's hook for bidirectional replies;
      * state_provider: async callable returning the source DT's current state, used
        by PULL and REQUEST_REPLY modes (usually a Layer 6.1 / 6.2 service call).
    """

    SOURCE_KIND: Optional[DTKind] = None
    TARGET_KIND: Optional[DTKind] = None
    OUT_CONTRACT: Optional[DataContract] = None
    IN_CONTRACT: Optional[DataContract] = None
    MODE: SyncMode = SyncMode.PUSH
    DIRECTION: Direction = Direction.UNIDIRECTIONAL

    def __init__(
        self,
        source: TwinEndpoint,
        target: TwinEndpoint,
        transport: Transport,
        *,
        policies: Optional[List[Policy]] = None,
        qos: Optional[QoS] = None,
        on_deliver_to_target: Optional[DeliverFn] = None,
        on_deliver_to_source: Optional[DeliverFn] = None,
        state_provider: Optional[StateFn] = None,
        purpose: str = "care",
        name: Optional[str] = None,
    ) -> None:
        if self.OUT_CONTRACT is None:
            raise TypeError(f"{type(self).__name__} must define OUT_CONTRACT")
        if self.SOURCE_KIND and source.kind != self.SOURCE_KIND:
            raise ValueError(f"{type(self).__name__} expects source {self.SOURCE_KIND}, got {source.kind}")
        if self.TARGET_KIND and target.kind != self.TARGET_KIND:
            raise ValueError(f"{type(self).__name__} expects target {self.TARGET_KIND}, got {target.kind}")
        if self.DIRECTION is Direction.BIDIRECTIONAL and self.IN_CONTRACT is None:
            raise TypeError(f"{type(self).__name__} is bidirectional and must define IN_CONTRACT")

        self.source, self.target, self.transport = source, target, transport
        self.policies = list(policies or [])
        self.qos = qos or QoS()
        self.on_deliver_to_target = on_deliver_to_target
        self.on_deliver_to_source = on_deliver_to_source
        self.state_provider = state_provider
        self.purpose = purpose
        self.name = name or f"{source.kind.value}->{target.kind.value}"
        self.connector_id = uuid.uuid4().hex[:12]

        self.state = ConnectorState.CREATED
        self._seq = 0
        self._last_sent = 0.0
        self._buffer: Deque[Tuple[str, bytes]] = deque(maxlen=self.qos.buffer_size)
        self._seen: Deque[str] = deque(maxlen=5000)
        self._seen_set: set = set()
        self._pending: Dict[str, asyncio.Future] = {}
        self.metrics: Dict[str, int] = defaultdict(int)
        self.audit: List[Dict[str, Any]] = []

    # ----- topic naming ---------------------------------------------------
    def topic(self, direction: str = "out") -> str:
        c = self.OUT_CONTRACT if direction == "out" else self.IN_CONTRACT
        a, b = (self.source, self.target) if direction == "out" else (self.target, self.source)
        return f"hdt/{a.hdt_id}/{a.kind.value}/to/{b.kind.value}/{c.name}/v{c.major}"

    def request_topic(self) -> str:
        return self.topic("out") + "/req"

    # ----- specialisation points -----------------------------------------
    @abc.abstractmethod
    def map_outbound(self, source_state: Mapping[str, Any]) -> Dict[str, Any]:
        """Transform source-DT state into an OUT_CONTRACT payload (units converted)."""

    def map_inbound(self, payload: Mapping[str, Any]) -> Dict[str, Any]:
        """Transform an IN_CONTRACT payload into an update for the source DT."""
        return dict(payload)

    def provenance(self, source_state: Mapping[str, Any]) -> Dict[str, Any]:
        """Model versions and other lineage for Layer 5 explanations. Override as needed."""
        return {"models": source_state.get("_models", {}), "connector": type(self).__name__}

    # ----- lifecycle ------------------------------------------------------
    async def start(self) -> None:
        await self.transport.connect()
        await self.transport.subscribe(self.topic("out"), self._on_raw_to_target)
        if self.DIRECTION is Direction.BIDIRECTIONAL:
            await self.transport.subscribe(self.topic("in"), self._on_raw_to_source)
        if self.MODE in (SyncMode.PULL, SyncMode.REQUEST_REPLY):
            await self.transport.subscribe(self.request_topic(), self._on_request)
        self.state = ConnectorState.RUNNING
        self._audit("start")

    async def stop(self) -> None:
        for fut in self._pending.values():
            if not fut.done():
                fut.cancel()
        self.state = ConnectorState.STOPPED
        self._audit("stop")

    # ----- outbound -------------------------------------------------------
    async def publish(self, source_state: Mapping[str, Any], *, sim_time: Optional[float] = None,
                      correlation_id: Optional[str] = None) -> Optional[Message]:
        """Send source-DT state to the target DT. Returns the message, or None if rate-limited."""
        self._require_running()
        if self.MODE is SyncMode.STREAM and self.qos.min_interval_s:
            now = time.monotonic()
            if now - self._last_sent < self.qos.min_interval_s:
                self.metrics["rate_limited"] += 1
                return None
            self._last_sent = now

        payload = self.map_outbound(source_state)
        self.OUT_CONTRACT.validate(payload)
        msg = self._envelope(payload, self.OUT_CONTRACT, self.source, self.target,
                             sim_time, correlation_id)
        msg.provenance.update(self.provenance(source_state))
        msg.provenance["content_hash"] = msg.content_hash()
        self._authorise(msg, "out")
        await self._send(self.topic("out"), msg)
        return msg

    async def reply(self, update: Mapping[str, Any], *, sim_time: Optional[float] = None) -> Message:
        """Target DT sends data back to the source DT (bidirectional connectors only)."""
        self._require_running()
        if self.DIRECTION is not Direction.BIDIRECTIONAL:
            raise RuntimeError(f"{self.name} is unidirectional")
        payload = dict(update)
        self.IN_CONTRACT.validate(payload)
        msg = self._envelope(payload, self.IN_CONTRACT, self.target, self.source, sim_time, None)
        msg.provenance["content_hash"] = msg.content_hash()
        self._authorise(msg, "out")
        await self._send(self.topic("in"), msg)
        return msg

    async def request(self, query: Optional[Mapping[str, Any]] = None) -> Message:
        """PULL / REQUEST_REPLY: ask the source DT for its current state; await the answer."""
        self._require_running()
        if self.MODE not in (SyncMode.PULL, SyncMode.REQUEST_REPLY):
            raise RuntimeError(f"{self.name} is {self.MODE.value}, not pull/request-reply")
        cid = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[cid] = fut
        req = json.dumps({"correlation_id": cid, "query": dict(query or {})}).encode()
        await self._send_raw(self.request_topic(), req)
        try:
            return await asyncio.wait_for(fut, self.qos.request_timeout_s)
        finally:
            self._pending.pop(cid, None)

    async def flush(self) -> int:
        """Re-send buffered messages after an outage. Returns number delivered."""
        sent = 0
        while self._buffer:
            topic, data = self._buffer[0]
            try:
                await self.transport.publish(topic, data)
            except Exception:
                return sent
            self._buffer.popleft()
            sent += 1
            self.metrics["flushed"] += 1
        if self.state is ConnectorState.DEGRADED:
            self.state = ConnectorState.RUNNING
        return sent

    # ----- inbound --------------------------------------------------------
    async def _on_raw_to_target(self, raw: bytes) -> None:
        await self._receive(raw, self.OUT_CONTRACT, self.on_deliver_to_target, to_source=False)

    async def _on_raw_to_source(self, raw: bytes) -> None:
        await self._receive(raw, self.IN_CONTRACT, self.on_deliver_to_source, to_source=True)

    async def _receive(self, raw: bytes, contract: DataContract,
                       deliver: Optional[DeliverFn], *, to_source: bool) -> None:
        try:
            msg = Message.from_bytes(raw)
            if msg.msg_id in self._seen_set:           # idempotent delivery
                self.metrics["duplicates"] += 1
                return
            self._remember(msg.msg_id)
            contract.validate(msg.payload)
            if msg.content_hash() != msg.provenance.get("content_hash"):
                raise ValueError("content hash mismatch")
            self._authorise(msg, "in")
            if to_source:
                msg.payload = self.map_inbound(msg.payload)
            if msg.correlation_id and msg.correlation_id in self._pending:
                fut = self._pending[msg.correlation_id]
                if not fut.done():
                    fut.set_result(msg)
            if deliver:
                await deliver(msg)
            self.metrics["received"] += 1
            self._audit("deliver", msg)
        except (ContractViolation, PolicyDenied, ValueError) as exc:
            self.metrics["rejected"] += 1
            self._audit("reject", None, error=str(exc))
            log.warning("%s rejected inbound message: %s", self.name, exc)

    async def _on_request(self, raw: bytes) -> None:
        req = json.loads(raw.decode())
        if self.state_provider is None:
            log.error("%s received a request but has no state_provider", self.name)
            return
        state = await self.state_provider()
        await self.publish(state, correlation_id=req["correlation_id"])

    # ----- internals ------------------------------------------------------
    def _envelope(self, payload: Dict[str, Any], contract: DataContract, src: TwinEndpoint,
                  tgt: TwinEndpoint, sim_time: Optional[float], cid: Optional[str]) -> Message:
        self._seq += 1
        return Message(source=src.uri, target=tgt.uri, contract=f"{contract.name}/v{contract.version}",
                       payload=payload, units=contract.units(), sim_time=sim_time,
                       correlation_id=cid, purpose=self.purpose, seq=self._seq,
                       provenance={"connector_id": self.connector_id})

    def _authorise(self, msg: Message, direction: str) -> None:
        for p in self.policies:
            d = p.evaluate(msg, direction)
            if not d.allowed:
                self.metrics["denied"] += 1
                self._audit("deny", msg, error=d.reason)
                raise PolicyDenied(f"{d.policy}: {d.reason}")

    async def _send(self, topic: str, msg: Message) -> None:
        await self._send_raw(topic, msg.to_bytes())
        self.metrics["sent"] += 1
        self._audit("send", msg)

    async def _send_raw(self, topic: str, data: bytes) -> None:
        delay = self.qos.backoff_s
        for attempt in range(self.qos.max_retries + 1):
            try:
                await self.transport.publish(topic, data)
                return
            except Exception as exc:  # transport-specific errors
                self.metrics["retries"] += 1
                if attempt == self.qos.max_retries:
                    self._buffer.append((topic, data))   # store-and-forward
                    self.state = ConnectorState.DEGRADED
                    self.metrics["buffered"] += 1
                    log.warning("%s buffered message after %d retries: %s", self.name, attempt, exc)
                    return
                await asyncio.sleep(delay)
                delay *= 2

    def _remember(self, msg_id: str) -> None:
        if len(self._seen) == self._seen.maxlen:
            self._seen_set.discard(self._seen[0])
        self._seen.append(msg_id)
        self._seen_set.add(msg_id)

    def _require_running(self) -> None:
        if self.state not in (ConnectorState.RUNNING, ConnectorState.DEGRADED):
            raise RuntimeError(f"{self.name} is {self.state.value}; call start() first")

    def _audit(self, event: str, msg: Optional[Message] = None, **extra: Any) -> None:
        rec = {"t": time.time(), "connector": self.name, "event": event, **extra}
        if msg is not None:
            rec.update(msg_id=msg.msg_id, trace_id=msg.trace_id, contract=msg.contract)
        self.audit.append(rec)

    def health(self) -> Dict[str, Any]:
        return {"connector": self.name, "id": self.connector_id, "state": self.state.value,
                "mode": self.MODE.value, "direction": self.DIRECTION.value,
                "buffered": len(self._buffer), **dict(self.metrics)}

    def describe(self) -> Dict[str, Any]:
        """Row for the coupling matrix."""
        return {"name": self.name, "source": self.source.kind.value, "target": self.target.kind.value,
                "mode": self.MODE.value, "direction": self.DIRECTION.value,
                "out": {"contract": f"{self.OUT_CONTRACT.name}/v{self.OUT_CONTRACT.version}",
                        "fields": self.OUT_CONTRACT.units()},
                "in": None if self.IN_CONTRACT is None else
                {"contract": f"{self.IN_CONTRACT.name}/v{self.IN_CONTRACT.version}",
                 "fields": self.IN_CONTRACT.units()}}


# ---------------------------------------------------------------------------
# 7. Connector manager (one per HDT) and coupling matrix
# ---------------------------------------------------------------------------

class ConnectorManager:
    """Registry and lifecycle manager for all connectors of one HDT (Layer 6.5)."""

    def __init__(self, hdt_id: str):
        self.hdt_id = hdt_id
        self._connectors: Dict[str, Connector] = {}

    def register(self, connector: Connector) -> Connector:
        if connector.source.hdt_id != self.hdt_id and connector.target.hdt_id != self.hdt_id:
            raise ValueError("connector does not belong to this HDT")
        if connector.name in self._connectors:
            raise ValueError(f"connector {connector.name} already registered")
        self._connectors[connector.name] = connector
        return connector

    def get(self, name: str) -> Connector:
        return self._connectors[name]

    async def start_all(self) -> None:
        for c in self._connectors.values():
            await c.start()

    async def stop_all(self) -> None:
        for c in self._connectors.values():
            await c.stop()

    async def flush_all(self) -> int:
        return sum([await c.flush() for c in self._connectors.values()])

    def coupling_matrix(self) -> Dict[str, Dict[str, List[str]]]:
        """{source_kind: {target_kind: [contract names]}} including reverse paths."""
        m: Dict[str, Dict[str, List[str]]] = defaultdict(lambda: defaultdict(list))
        for c in self._connectors.values():
            m[c.source.kind.value][c.target.kind.value].append(c.OUT_CONTRACT.name)
            if c.DIRECTION is Direction.BIDIRECTIONAL:
                m[c.target.kind.value][c.source.kind.value].append(c.IN_CONTRACT.name)
        return {k: dict(v) for k, v in m.items()}

    def health(self) -> List[Dict[str, Any]]:
        return [c.health() for c in self._connectors.values()]


# ---------------------------------------------------------------------------
# 8. Example specialisations
# ---------------------------------------------------------------------------

class CardiovascularRespiratoryConnector(Connector):
    """Oxygen delivery <-> gas exchange coupling.

    Out (Cardiovascular -> Respiratory): cardiac output, heart rate, mean arterial pressure.
    In  (Respiratory -> Cardiovascular): SpO2, arterial O2 and CO2 partial pressures, resp. rate.
    Stream mode, typically every 1-5 s from wearables; min_interval_s rate-limits bursts.
    """

    SOURCE_KIND = DTKind.CARDIOVASCULAR
    TARGET_KIND = DTKind.RESPIRATORY
    MODE = SyncMode.STREAM
    DIRECTION = Direction.BIDIRECTIONAL
    OUT_CONTRACT = DataContract("haemodynamics", "1.0", {
        "cardiac_output": FieldSpec("float", "L/min", min=0.5, max=40),
        "heart_rate": FieldSpec("float", "/min", min=20, max=250),
        "mean_arterial_pressure": FieldSpec("float", "mm[Hg]", min=20, max=200),
    })
    IN_CONTRACT = DataContract("gas_exchange", "1.0", {
        "spo2": FieldSpec("float", "%", min=50, max=100),
        "pao2": FieldSpec("float", "mm[Hg]", required=False, min=20, max=600),
        "paco2": FieldSpec("float", "mm[Hg]", required=False, min=10, max=150),
        "respiratory_rate": FieldSpec("float", "/min", min=4, max=70),
    })

    def map_outbound(self, s: Mapping[str, Any]) -> Dict[str, Any]:
        # Source DT holds stroke volume in mL; contract wants cardiac output in L/min.
        hr = float(s["heart_rate_bpm"])
        co = float(s["stroke_volume_ml"]) * hr / 1000.0
        # MAP ~= DBP + (SBP - DBP) / 3 when only cuff pressures are available.
        mapp = s.get("map_mmhg")
        if mapp is None:
            mapp = s["dbp_mmhg"] + (s["sbp_mmhg"] - s["dbp_mmhg"]) / 3.0
        return {"cardiac_output": round(co, 2), "heart_rate": hr,
                "mean_arterial_pressure": round(float(mapp), 1)}

    def map_inbound(self, p: Mapping[str, Any]) -> Dict[str, Any]:
        # Cardiovascular DT stores oxygen saturation as a fraction.
        out = dict(p)
        out["sao2_fraction"] = round(p["spo2"] / 100.0, 3)
        return out


class EndocrineBehaviouralConnector(Connector):
    """Metabolic and stress state <-> behaviour.

    Out (Endocrine -> Behavioural): glucose, time in range, cortisol-based stress index.
    In  (Behavioural -> Endocrine): activity minutes, sleep hours, meal carbohydrate, adherence.
    """

    SOURCE_KIND = DTKind.ENDOCRINE
    TARGET_KIND = DTKind.BEHAVIOURAL_COGNITIVE
    MODE = SyncMode.PUSH
    DIRECTION = Direction.BIDIRECTIONAL
    OUT_CONTRACT = DataContract("metabolic_stress_state", "1.1", {
        "glucose": FieldSpec("float", "mmol/L", min=1.0, max=35.0),
        "time_in_range_24h": FieldSpec("float", "%", min=0, max=100),
        "stress_index": FieldSpec("float", "1", required=False, min=0, max=1),
    })
    IN_CONTRACT = DataContract("behaviour_summary", "1.0", {
        "active_minutes_24h": FieldSpec("float", "min", min=0, max=1440),
        "sleep_hours": FieldSpec("float", "h", min=0, max=24),
        "carbohydrate_g": FieldSpec("float", "g", required=False, min=0, max=1000),
        "medication_adherence": FieldSpec("float", "1", required=False, min=0, max=1),
    })

    MGDL_PER_MMOLL = 18.0

    def map_outbound(self, s: Mapping[str, Any]) -> Dict[str, Any]:
        glucose = s.get("glucose_mmol_l")
        if glucose is None:                       # CGMs in some markets report mg/dL
            glucose = s["glucose_mg_dl"] / self.MGDL_PER_MMOLL
        out = {"glucose": round(float(glucose), 1),
               "time_in_range_24h": float(s["tir_pct"])}
        if "cortisol_z" in s:                     # squash z-score to [0, 1]
            z = max(-3.0, min(3.0, float(s["cortisol_z"])))
            out["stress_index"] = round((z + 3.0) / 6.0, 2)
        return out


class IndividualToPopulationConnector(Connector):
    """De-identified contribution from an individual's Whole-Body DT to the Population DT.

    Direct identifiers never leave; age is generalised to 5-year bands and location to
    state level before the contract is validated.
    """

    SOURCE_KIND = DTKind.WHOLE_BODY
    TARGET_KIND = DTKind.POPULATION
    MODE = SyncMode.PUSH
    DIRECTION = Direction.UNIDIRECTIONAL
    OUT_CONTRACT = DataContract("cohort_contribution", "1.0", {
        "age_band": FieldSpec("str"),
        "sex": FieldSpec("str"),
        "state": FieldSpec("str"),
        "conditions": FieldSpec("list"),
        "bmi": FieldSpec("float", "kg/m2", required=False, min=10, max=80),
    })

    def map_outbound(self, s: Mapping[str, Any]) -> Dict[str, Any]:
        lo = (int(s["age_years"]) // 5) * 5
        out = {"age_band": f"{lo}-{lo + 4}", "sex": s["sex"],
               "state": s["address"]["state"],               # drop street, LGA, ward
               "conditions": sorted(s.get("condition_codes", []))}
        if s.get("weight_kg") and s.get("height_m"):
            out["bmi"] = round(s["weight_kg"] / s["height_m"] ** 2, 1)
        return out

    def provenance(self, s: Mapping[str, Any]) -> Dict[str, Any]:
        return {"connector": type(self).__name__, "deidentification": "age-band-5y,state-level"}


# ---------------------------------------------------------------------------
# 9. Demo
# ---------------------------------------------------------------------------

async def _demo() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    hdt = "hdt-7f3a91"
    bus = InMemoryTransport()
    consent = ConsentPolicy({
        (DTKind.CARDIOVASCULAR, DTKind.RESPIRATORY): {"care"},
        (DTKind.RESPIRATORY, DTKind.CARDIOVASCULAR): {"care"},
        (DTKind.ENDOCRINE, DTKind.BEHAVIOURAL_COGNITIVE): {"care"},
        (DTKind.BEHAVIOURAL_COGNITIVE, DTKind.ENDOCRINE): {"care"},
        (DTKind.WHOLE_BODY, DTKind.POPULATION): {"public_health"},
    })

    async def show(label: str) -> DeliverFn:
        async def _f(m: Message) -> None:
            print(f"  [{label}] {m.contract} seq={m.seq} payload={m.payload}")
        return _f

    mgr = ConnectorManager(hdt)
    cv_rs = mgr.register(CardiovascularRespiratoryConnector(
        TwinEndpoint(hdt, DTKind.CARDIOVASCULAR), TwinEndpoint(hdt, DTKind.RESPIRATORY), bus,
        policies=[consent], on_deliver_to_target=await show("Respiratory DT"),
        on_deliver_to_source=await show("Cardiovascular DT")))
    en_bh = mgr.register(EndocrineBehaviouralConnector(
        TwinEndpoint(hdt, DTKind.ENDOCRINE), TwinEndpoint(hdt, DTKind.BEHAVIOURAL_COGNITIVE), bus,
        policies=[consent], on_deliver_to_target=await show("Behavioural DT"),
        on_deliver_to_source=await show("Endocrine DT")))
    wb_pop = mgr.register(IndividualToPopulationConnector(
        TwinEndpoint(hdt, DTKind.WHOLE_BODY), TwinEndpoint("cohort-lagos", DTKind.POPULATION), bus,
        policies=[consent], purpose="public_health", on_deliver_to_target=await show("Population DT")))
    await mgr.start_all()

    print("Cardiovascular -> Respiratory, and reply")
    await cv_rs.publish({"heart_rate_bpm": 72, "stroke_volume_ml": 70, "sbp_mmhg": 124,
                         "dbp_mmhg": 82, "_models": {"heart": "lumped-4E v2.3"}}, sim_time=0.0)
    await cv_rs.reply({"spo2": 97.0, "respiratory_rate": 14.0})

    print("Endocrine -> Behavioural, and reply")
    await en_bh.publish({"glucose_mg_dl": 162, "tir_pct": 68, "cortisol_z": 1.2})
    await en_bh.reply({"active_minutes_24h": 35, "sleep_hours": 6.2, "medication_adherence": 0.9})

    print("Whole-Body -> Population (de-identified)")
    await wb_pop.publish({"age_years": 47, "sex": "female",
                          "address": {"street": "12 Example Rd", "lga": "Yaba", "state": "Lagos"},
                          "condition_codes": ["44054006"], "weight_kg": 78, "height_m": 1.63})

    print("Contract violation is refused at the source:")
    try:
        await cv_rs.publish({"heart_rate_bpm": 400, "stroke_volume_ml": 70, "map_mmhg": 90})
    except ContractViolation as e:
        print("  refused:", e)

    print("Coupling matrix:", json.dumps(mgr.coupling_matrix(), indent=2))
    print("Health:", json.dumps(mgr.health(), indent=2))
    await mgr.stop_all()


if __name__ == "__main__":
    asyncio.run(_demo())
