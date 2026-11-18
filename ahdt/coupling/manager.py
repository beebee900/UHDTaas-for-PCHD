"""One `ConnectorManager` per HDT, built from the twin definitions (design 04, 4.8)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ahdt.coupling.base import CoupledConnector, QueryFn
from ahdt.coupling.connectors import connector_class
from ahdt.coupling.inbox import REORDER_WINDOW_S, CouplingInbox
from ahdt.coupling.policies import connector_policies, purpose_of, spec_of
from ahdt.coupling.state import TwinStateProvider
from ahdt.registry import Registry, load_registry
from atra.backends.base import EventBusBackend
from atra.connection import dlq_topic
from atra.connector_contracts import expanded_pairs
from atra.connectors import (
    ConnectorManager,
    ContractViolation,
    Direction,
    DTKind,
    Message,
    PolicyDenied,
    QoS,
    SyncMode,
    Transport,
    TwinEndpoint,
)
from atra.consent import ConsentRegistry
from atra.policy import SyncPolicyClient


def connector_name(spec_name: str, source: DTKind, target: DTKind) -> str:
    return f"{spec_name}:{source.value}->{target.value}"


def hdt_pairs(registry: Registry) -> list[tuple[str, DTKind, DTKind]]:
    """Concrete connectors of one HDT: those its twin definitions list, in or out."""
    out = []
    for name, source, target in expanded_pairs():
        src, tgt = registry.get(source), registry.get(target)
        if (src and name in src.connectors_out) or (tgt and name in tgt.connectors_in):
            out.append((name, source, target))
    return out


@dataclass
class PublishResult:
    connector: str
    message: Message | None = None
    error: str | None = None


@dataclass
class HDTCoupling:
    """The connectors, inbox and lifecycle of one person's HDT."""

    hdt_id: str
    manager: ConnectorManager
    inbox: CouplingInbox
    connectors: dict[str, CoupledConnector] = field(default_factory=dict)
    states: TwinStateProvider | None = None
    running: bool = False

    async def start(self) -> None:
        await self.manager.start_all()
        self.running = True

    async def stop(self) -> None:
        await self.inbox.flush()
        await self.manager.flush_all()
        await self.manager.stop_all()
        self.running = False

    def get(self, spec_name: str, source: DTKind, target: DTKind) -> CoupledConnector:
        return self.connectors[connector_name(spec_name, source, target)]

    def outgoing(self, kind: DTKind) -> list[CoupledConnector]:
        return [c for c in self.connectors.values() if c.source.kind is kind]

    async def publish_from(self, kind: DTKind, state: Mapping[str, Any] | None = None, *,
                           sim_time: float | None = None) -> list[PublishResult]:
        """Push the twin's state on each of its push and stream connectors.

        Refusals are dead-lettered by the connector and reported here, so one refused
        contract does not stop the others.
        """
        if state is None:
            if self.states is None:
                raise RuntimeError("no state provider for this HDT")
            state = await self.states.state(self.hdt_id, kind)
        results = []
        for c in self.outgoing(kind):
            if c.MODE not in (SyncMode.PUSH, SyncMode.STREAM):
                continue
            try:
                results.append(PublishResult(c.name, await c.publish(state, sim_time=sim_time)))
            except (ContractViolation, PolicyDenied) as exc:
                results.append(PublishResult(c.name, error=str(exc)))
        return results

    def view(self) -> dict[str, Any]:
        """The coupling matrix of this HDT and one row per connector."""
        rows = []
        for c in self.connectors.values():
            spec = spec_of(c.spec_name())
            bidirectional = c.DIRECTION is Direction.BIDIRECTIONAL
            health = c.health()
            rows.append({
                **c.describe(),
                "connector": c.spec_name(),
                "purpose": c.purpose,
                "purposes": sorted(spec.purposes),
                "topics": {"out": c.topic("out"),
                           "in": c.topic("in") if bidirectional else None,
                           "dlq": dlq_topic(c.topic("out"))},
                "state": health["state"],
                "buffered": health["buffered"],
                "metrics": {k: v for k, v in health.items() if isinstance(v, int)
                            and k not in ("buffered",)},
            })
        return {"hdt_id": self.hdt_id, "running": self.running, "count": len(rows),
                "connectors": rows, "matrix": self.manager.coupling_matrix()}


def build_coupling(hdt_id: str, transport: Transport, *, consents: ConsentRegistry,
                   registry: Registry | None = None, opa: SyncPolicyClient | None = None,
                   states: TwinStateProvider | None = None,
                   query_providers: Mapping[str, QueryFn] | None = None,
                   events: EventBusBackend | None = None,
                   window_s: float = REORDER_WINDOW_S, qos: QoS | None = None) -> HDTCoupling:
    """Every connector the twin definitions list, wired to policies, inbox and DLQ events.

    `query_providers` answer request-reply connectors by 3.16 name (the Population twin's
    priors and norms); otherwise the source twin's state answers.
    """
    registry = registry or load_registry()
    inbox = CouplingInbox(hdt_id, window_s=window_s, events=events)
    coupling = HDTCoupling(hdt_id, ConnectorManager(hdt_id), inbox, states=states)
    policies = connector_policies(hdt_id, consents, opa)
    for spec_name, source, target in hdt_pairs(registry):
        cls = connector_class(spec_name, source)
        name = connector_name(spec_name, source, target)
        connector = cls(
            TwinEndpoint(hdt_id, source), TwinEndpoint(hdt_id, target), transport,
            policies=policies, qos=qos, purpose=purpose_of(spec_of(spec_name)), name=name,
            state_provider=states.provider(hdt_id, source) if states else None,
            query_provider=(query_providers or {}).get(spec_name),
            on_dead_letter=inbox.dead_lettered)
        connector.on_deliver_to_target = inbox.deliver_fn(connector, spec_name, to_source=False)
        if connector.DIRECTION is Direction.BIDIRECTIONAL:
            connector.on_deliver_to_source = inbox.deliver_fn(connector, spec_name,
                                                              to_source=True)
        coupling.manager.register(connector)
        coupling.connectors[name] = connector
    return coupling
