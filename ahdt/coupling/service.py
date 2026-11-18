"""Coupling service of the AHDT process and the coupling matrix route."""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from typing import Any

from fastapi import FastAPI, Request
from pydantic import BaseModel, Field

from ahdt.coupling.base import QueryFn
from ahdt.coupling.manager import HDTCoupling, build_coupling
from ahdt.coupling.registration import register_contracts
from ahdt.coupling.state import TwinStateProvider
from ahdt.coupling.transport import SharedTransport
from ahdt.registry import Registry, load_registry
from atra.backends import Backends
from atra.consent import ConsentRegistry
from atra.contracts import Role
from atra.policy import SyncPolicyClient
from atra.service import Problem, authenticate, verifier_of

log = logging.getLogger("ahdt.coupling")

VIEW_ROLES = frozenset({Role.ADMINISTRATOR, Role.CLINICAL_SAFETY_OFFICER,
                        Role.MEDICAL_OFFICER, Role.NURSE})


class CouplingService:
    """The running HDTs of this process, one `HDTCoupling` each."""

    def __init__(self, backends: Backends, consents: ConsentRegistry, *,
                 registry: Registry | None = None, states: TwinStateProvider | None = None,
                 query_providers: Mapping[str, QueryFn] | None = None) -> None:
        self.backends = backends
        self.consents = consents
        self.registry = registry or load_registry()
        self.states = states
        self.query_providers = query_providers
        self.hdts: dict[str, HDTCoupling] = {}
        self._transport: SharedTransport | None = None
        self._opa: SyncPolicyClient | None = None
        self._registered = False

    @property
    def transport(self) -> SharedTransport:
        if self._transport is None:
            self._transport = SharedTransport(self.backends.transport)
        return self._transport

    async def start(self, hdt_id: str) -> HDTCoupling:
        if hdt_id in self.hdts:
            return self.hdts[hdt_id]
        if not self._registered:
            await register_contracts(self.backends.schemas)
            self._registered = True
        if self._opa is None:
            self._opa = SyncPolicyClient(self.backends.settings.infra.opa)
        coupling = build_coupling(
            hdt_id, self.transport, consents=self.consents, registry=self.registry,
            opa=self._opa, states=self.states, query_providers=self.query_providers,
            events=self.backends.events)
        await coupling.start()
        self.hdts[hdt_id] = coupling
        return coupling

    async def start_all(self, hdt_ids: Iterable[str]) -> None:
        for hdt_id in hdt_ids:
            await self.start(hdt_id)

    def get(self, hdt_id: str) -> HDTCoupling | None:
        return self.hdts.get(hdt_id)

    async def stop(self) -> None:
        for coupling in self.hdts.values():
            await coupling.stop()
        self.hdts.clear()
        if self._transport is not None:
            await self._transport.close()
        if self._opa is not None:
            self._opa.close()
            self._opa = None


class ContractRef(BaseModel):
    contract: str = Field(description="<name>/v<version>")
    fields: dict[str, str | None] = Field(description="Field name to UCUM unit")


class ConnectorTopics(BaseModel):
    out: str
    in_: str | None = Field(None, alias="in")
    dlq: str


class ConnectorRow(BaseModel):
    name: str = Field(description="<connector>:<source>-><target>")
    connector: str = Field(description="Connector name in design 03, 3.16")
    source: str
    target: str
    mode: str
    direction: str
    out: ContractRef
    in_: ContractRef | None = Field(None, alias="in")
    purpose: str
    purposes: list[str]
    topics: ConnectorTopics
    state: str
    buffered: int
    metrics: dict[str, int]


class CouplingMatrix(BaseModel):
    hdt_id: str
    running: bool
    count: int
    connectors: list[ConnectorRow]
    matrix: dict[str, dict[str, list[str]]] = Field(
        description="source twin -> target twin -> contract names, reverse paths included")


def mount_coupling(app: FastAPI, service: CouplingService) -> None:
    @app.get("/v1/persons/{hdt_id}/coupling", tags=["coupling"],
             summary="Connectors and coupling matrix of the person's running HDT",
             response_model=CouplingMatrix, response_model_by_alias=True)
    async def coupling(hdt_id: str, request: Request) -> Any:
        ident = await authenticate(request.headers, await verifier_of(app), hdt_id=hdt_id)
        own = ident.claims.hdt_id == hdt_id and not ident.delegated
        if not own and ident.ctx.actor_role not in VIEW_ROLES:
            raise Problem(403, "forbidden", "this role may not view the coupling")
        running = service.get(hdt_id)
        if running is None:
            raise Problem(404, "not-found", f"no running HDT {hdt_id}")
        return running.view()
