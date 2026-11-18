"""AHDT service: Layer 6 tools over REST and MCP, A2A agents, operations routes (port 8100)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from ahdt.agents.hub import AgentHub
from ahdt.agents.routes import mount_agents
from ahdt.coupling.service import CouplingService, mount_coupling
from ahdt.coupling.state import TwinStateProvider, output_units
from ahdt.ingest import mount_import, pipeline_of
from ahdt.knowledge.service import KnowledgeService, mount_export
from ahdt.models.language.converse import build_converser
from ahdt.models.language.status import mount_language_status
from ahdt.registry import load_registry
from ahdt.services import Services, build_services
from ahdt.services.dapr import mount_dapr
from ahdt.services.fhir import mount_fhir
from ahdt.services.graphql import mount_graphql
from ahdt.services.identity import mount_identity
from ahdt.services.lifecycle import DriftMonitor, mount_lifecycle
from ahdt.services.runtime import Runtime
from ahdt.services.write_back import mount_write_back
from ahdt.workers.auto_explain import AutoExplainWorker
from atra import contracts as c
from atra.backends import Backends
from atra.config import Settings, get_settings
from atra.connectors import DTKind
from atra.consent import ConsentRegistry, demo_registry
from atra.gateway import AHDT_TOOLS
from atra.policy import PolicyDecision
from atra.schemagen import MCP_SERVERS, tool_descriptor
from atra.service import (
    Identity,
    McpMount,
    SkillSpec,
    ToolExecutor,
    create_app,
    mount_a2a,
    mount_mcp,
    mount_tools,
    verifier_of,
)

CONDUCTOR_SKILLS = (
    SkillSpec("submit_goal", "Accept a goal for one person's twins and plan it"),
    SkillSpec("get_status", "Status of a submitted goal"),
    SkillSpec("arbitrate", "Resolve conflicting plans from several twins"),
)
ORCHESTRATOR_SKILLS = (
    SkillSpec("get_goals", "Standing goals of this twin"),
    SkillSpec("report", "Latest goal report of this twin"),
)
PERSON_TWINS = tuple(k for k in DTKind if k.is_ahdt_member and k is not DTKind.POPULATION)


def build_app(settings: Settings | None = None, *, backends: Backends | None = None,
              consents: ConsentRegistry | None = None, local_llm: bool = True) -> FastAPI:
    settings = settings or get_settings()

    async def startup(app: FastAPI) -> None:
        pipeline = await pipeline_of(app)
        if settings.ahdt.grpc_port is not None:
            from ahdt import grpc_server

            app.state.grpc, app.state.grpc_port = await grpc_server.start(
                pipeline, await verifier_of(app), settings.ahdt.grpc_port,
                app.state.services.model.infer)
        await app.state.coupling.start_all(app.state.consents.as_mapping())

    async def shutdown(app: FastAPI) -> None:
        await app.state.coupling.stop()
        if getattr(app.state, "grpc", None) is not None:
            await app.state.grpc.stop(grace=1)

    app = create_app("ahdt", settings, backends=backends, version=settings.ahdt_version,
                     title="AHDT", on_startup=startup, on_shutdown=shutdown,
                     description="Agentic Human Digital Twin: Layer 6 services and Layer 7 agents")
    app.state.consents = consents or demo_registry()
    app.state.registry = load_registry()
    ready: Backends = app.state.backends
    consent_registry: ConsentRegistry = app.state.consents

    async def authorise(tool: str, args: BaseModel, ident: Identity) -> PolicyDecision:
        hdt_id = str(getattr(args, "hdt_id", ""))
        consent = consent_registry.get(hdt_id)
        return await ready.policy.decide("ahdt.tools", {
            "tool": tool, "role": ident.ctx.actor_role.value, "purpose": ident.ctx.purpose,
            "hdt_id": hdt_id, "claims": ident.claims.policy_view(),
            "delegated": ident.delegated, "consent": ConsentRegistry.policy_view(consent),
            "args": args.model_dump(mode="json", by_alias=True, exclude={"hdt_id"})})

    async def verifier() -> Any:
        return await verifier_of(app)

    knowledge = KnowledgeService(ready)
    knowledge.subscribe()
    app.state.knowledge = knowledge
    runtime = Runtime(backends=ready, consents=consent_registry, audit=app.state.audit,
                      settings=settings, registry=app.state.registry,
                      pipeline=lambda: pipeline_of(app),
                      make_converser=lambda: build_converser(settings, local=local_llm))
    services: Services = build_services(runtime, localise_with_model=local_llm)
    app.state.runtime = runtime
    app.state.services = services
    AutoExplainWorker(services).subscribe()
    hub = AgentHub(services, app.state.registry)
    app.state.agents = hub
    executor = ToolExecutor(
        service="ahdt", version=settings.ahdt_version, args=c.TOOL_ARGS,
        responses=c.TOOL_RESPONSES, handlers={**services.handlers(), **knowledge.handlers()},
        authorise=authorise,
        audit=app.state.audit, verifier=verifier,
        descriptions={t.name: t.description for t in AHDT_TOOLS},
        forced_fork=frozenset(t.name for t in AHDT_TOOLS if t.forces_fork))
    app.state.executor = executor
    mount_tools(app, executor)
    mount_agents(app, hub)
    mount_import(app)
    mount_fhir(app)
    mount_write_back(app)
    mount_graphql(app, executor)
    mount_dapr(app, ready)
    mount_identity(app)
    mount_lifecycle(app, runtime)
    mount_language_status(app, runtime)
    app.state.drift = DriftMonitor(runtime)
    mount_export(app, knowledge)
    states = TwinStateProvider(runtime.store, units=output_units(runtime.catalogue),
                               registry=app.state.registry, fields=runtime.twin_fields)
    app.state.coupling = CouplingService(ready, consent_registry, registry=app.state.registry,
                                         states=states)
    mount_coupling(app, app.state.coupling)

    descriptors = {t.name: tool_descriptor(t) for t in AHDT_TOOLS}
    for server, sublayer in MCP_SERVERS.items():
        tools = [t.name for t in AHDT_TOOLS if t.sublayer == sublayer]
        path = "/mcp/" + server.removeprefix("ahdt-")
        mount_mcp(app, path, McpMount(server, executor, tools, descriptors))

    base = settings.services.ahdt
    mount_a2a(app, base, "ahdt-conductor", "Conductor of one person's AHDT orchestrators",
              CONDUCTOR_SKILLS, _conductor_skill(hub), version=settings.ahdt_version)
    for kind in PERSON_TWINS:
        mount_a2a(app, base, f"ahdt-orchestrator-{kind.value}",
                  f"Orchestrator of the {kind.value.replace('_', ' ')} twin", ORCHESTRATOR_SKILLS,
                  _orchestrator_skill(kind, app, hub), version=settings.ahdt_version)
    return app


def _conductor_skill(hub: AgentHub) -> Any:
    async def handle(skill: str, args: Mapping[str, Any]) -> dict[str, Any]:
        if skill == "arbitrate":
            return hub.conductor.arbitrate(list(args.get("plans", ()))).dump()
        hdt_id = str(args.get("hdt_id", ""))
        if skill == "get_status":
            last = hub.conductor.last_status.get(hdt_id)
            return {"hdt_id": hdt_id, "status": last["status"] if last else "unknown"}
        return {"goal_id": str(args.get("goal_id", "goal-stub")), "status": "accepted"}

    return handle


def _orchestrator_skill(kind: DTKind, app: FastAPI, hub: AgentHub) -> Any:
    async def handle(skill: str, args: Mapping[str, Any]) -> dict[str, Any]:
        definition = app.state.registry.get(kind)
        goals = [g.model_dump(mode="json") for g in definition.standing_goals] if definition else []
        if skill == "get_goals":
            return {"twin": kind.value, "goals": goals}
        last = hub.reports.get((str(args.get("hdt_id", "")), kind.value))
        return last or {"twin": kind.value, "status": "no report yet"}

    return handle
