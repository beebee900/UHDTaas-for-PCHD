"""Additions to the supplied `Connector` that leave its class unchanged (design 03, 3.11).

- `ProvenanceStampMixin` adds `hlc` and `prov_id` to every message's provenance and
  advances the twin's hybrid logical clock on receipt.
- `DeadLetterMixin` sends refused messages to `<topic>.dlq` for review.

Mix them in before the connector class: `class C(DeadLetterMixin, ProvenanceStampMixin, X)`.

`ConnectorEnvelope` and `DeadLetterRecord` are the wire shapes of a message and of a
dead-letter record; `atra.schemagen` publishes them next to the connector contracts.
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from atra.clock import HybridLogicalClock
from atra.connectors import (
    Connector,
    ContractViolation,
    DataContract,
    Message,
    PolicyDenied,
    TwinEndpoint,
)
from atra.provenance import ProvenanceStore

type DeadLetterFn = Callable[[Mapping[str, Any]], Awaitable[None]]

WIRE_VERSION = "1.0"


class ConnectorEnvelope(BaseModel):
    """A connector message on the wire (`Message.to_bytes`)."""

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="TwinEndpoint URI hdt://<hdt_id>/<kind>/<instance>")
    target: str
    contract: str = Field(pattern=r"^[a-z0-9_]+/v[0-9]+\.[0-9]+$")
    payload: dict[str, Any]
    units: dict[str, str | None] = Field(description="UCUM unit per payload field")
    sim_time: float | None = None
    wall_time: float
    msg_id: str
    trace_id: str
    correlation_id: str | None = None
    reply_to: str | None = None
    purpose: str
    provenance: dict[str, Any] = Field(
        description="connector_id, connector, models, content_hash, hlc, prov_id")
    seq: int = Field(ge=0)


class DeadLetterRecord(BaseModel):
    """A refused message as published to `<topic>.dlq`."""

    model_config = ConfigDict(extra="forbid")

    t: float = Field(description="Unix time of the refusal")
    connector: str
    topic: str = Field(description="The topic the message was refused on")
    direction: Literal["in", "out"]
    reason: str
    source_state: dict[str, Any] | None = Field(
        None, description="Outbound refusals: the state the connector tried to send")
    message: dict[str, Any] | str | None = Field(
        None, description="Inbound refusals: the received envelope, or its text if unreadable")


def dlq_topic(topic: str) -> str:
    return f"{topic}.dlq"


class ProvenanceStampMixin(Connector):
    """Stamps `hlc` and `prov_id` on outgoing messages and updates the HLC on receipt."""

    def __init__(self, *args: Any, hlc: HybridLogicalClock | None = None,
                 provenance_store: ProvenanceStore | None = None, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.hlc = hlc or HybridLogicalClock(f"{self.source.kind.value}-{self.connector_id}")
        self.provenance_store = provenance_store

    def _envelope(self, payload: dict[str, Any], contract: DataContract, src: TwinEndpoint,
                  tgt: TwinEndpoint, sim_time: float | None, cid: str | None) -> Message:
        msg = super()._envelope(payload, contract, src, tgt, sim_time, cid)
        msg.provenance["hlc"] = str(self.hlc.now())
        if self.provenance_store is not None:
            entity = self.provenance_store.entity(f"msg-{msg.msg_id}", "message",
                                                  contract=msg.contract, source=msg.source,
                                                  target=msg.target)
            self.provenance_store.activity("transfer", generated=[entity],
                                           connector=type(self).__name__)
            msg.provenance["prov_id"] = entity
        else:
            msg.provenance["prov_id"] = f"atra:msg-{msg.msg_id}"
        return msg

    async def _receive(self, raw: bytes, contract: DataContract, deliver: Any, *,
                       to_source: bool) -> None:
        try:
            stamp = json.loads(raw.decode()).get("provenance", {}).get("hlc")
        except (ValueError, AttributeError):
            stamp = None
        if isinstance(stamp, str):
            self.hlc.update(stamp)
        await super()._receive(raw, contract, deliver, to_source=to_source)


class DeadLetterMixin(Connector):
    """Publishes refused messages to the dead-letter topic `<topic>.dlq`.

    Outbound refusals (contract or policy) are dead-lettered and then raised, as before.
    Inbound rejections are dead-lettered after the supplied pipeline has audited them.
    """

    def __init__(self, *args: Any, on_dead_letter: DeadLetterFn | None = None,
                 **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.on_dead_letter = on_dead_letter
        self.dead_letters: list[dict[str, Any]] = []

    async def publish(self, source_state: Mapping[str, Any], *, sim_time: float | None = None,
                      correlation_id: str | None = None) -> Message | None:
        try:
            return await super().publish(source_state, sim_time=sim_time,
                                         correlation_id=correlation_id)
        except (ContractViolation, PolicyDenied) as exc:
            await self._dead_letter(self.topic("out"), "out", str(exc),
                                    {"source_state": dict(source_state)})
            raise

    async def _on_raw_to_target(self, raw: bytes) -> None:
        await self._watch(self.topic("out"), raw, super()._on_raw_to_target)

    async def _on_raw_to_source(self, raw: bytes) -> None:
        await self._watch(self.topic("in"), raw, super()._on_raw_to_source)

    async def _watch(self, topic: str, raw: bytes,
                     handler: Callable[[bytes], Awaitable[None]]) -> None:
        before = self.metrics["rejected"]
        await handler(raw)
        if self.metrics["rejected"] > before:
            reason = next((a.get("error", "") for a in reversed(self.audit)
                           if a["event"] == "reject"), "rejected")
            try:
                message: Any = json.loads(raw.decode())
            except ValueError:
                message = raw.decode(errors="replace")
            await self._dead_letter(topic, "in", reason, {"message": message})

    async def _dead_letter(self, topic: str, direction: str, reason: str,
                           body: Mapping[str, Any]) -> None:
        record = {"t": time.time(), "connector": self.name, "topic": topic,
                  "direction": direction, "reason": reason, **body}
        self.dead_letters.append(record)
        self.metrics["dead_lettered"] += 1
        try:
            await self.transport.publish(dlq_topic(topic),
                                         json.dumps(record, default=str).encode())
        except Exception as exc:  # the DLQ must never hide the original refusal
            self._audit("dlq_failed", None, error=str(exc))
        self._audit("dead_letter", None, error=reason, topic=topic)
        if self.on_dead_letter is not None:
            await self.on_dead_letter(record)
