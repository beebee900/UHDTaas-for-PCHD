"""Population service: priors, norms and contributions over REST and MCP (port 8110)."""

from __future__ import annotations

import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from atra import contracts as c
from atra.backends import Backends
from atra.config import Settings, get_settings
from atra.kb import KnowledgeBase
from atra.policy import PolicyDecision
from atra.schemagen import POPULATION_DESCRIPTIONS, service_tool_descriptor
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
from population.cohort import CohortStore, k_min
from population.federated import PrivacyLedger
from population.priors import PopulationPriors
from population.service import PopulationService

ORCHESTRATOR_SKILLS = (
    SkillSpec("get_goals", "Standing goals of the Population twin"),
    SkillSpec("report", "Latest goal report of the Population twin"),
)


def build_service(settings: Settings, backends: Backends,
                  models_root: Path | None = None) -> PopulationService:
    """Priors from the trained model under `models_root` (default `<var_dir>/models/t1`),
    the cohort store in the service's data directory, and the privacy ledger."""
    kb = KnowledgeBase(settings.kb_dir)
    lake_dir = (Path(tempfile.mkdtemp(prefix="atra-population-lake-")) if backends.ephemeral
                else backends.data_dir / "population_lake")
    root = models_root or settings.var_dir / "models" / "t1"
    return PopulationService(PopulationPriors.load(kb, root),
                             CohortStore(lake_dir, k_min(kb)), PrivacyLedger.from_kb(kb), kb)


def build_app(settings: Settings | None = None, *, backends: Backends | None = None,
              models_root: Path | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = create_app("population", settings, backends=backends, title="Population twin",
                     description="Population twin: priors, norms, cohorts and contributions")
    ready: Backends = app.state.backends
    service = build_service(settings, ready, models_root)
    app.state.population = service

    async def authorise(tool: str, args: BaseModel, ident: Identity) -> PolicyDecision:
        return await ready.policy.decide("population.tools", {
            "tool": tool, "role": ident.ctx.actor_role.value, "service": ident.delegated,
            "claims": ident.claims.policy_view()})

    async def verifier() -> Any:
        return await verifier_of(app)

    executor = ToolExecutor(
        service="population", version="1.0.0", args=c.POPULATION_TOOL_ARGS,
        responses=c.POPULATION_TOOL_RESPONSES, handlers=service.handlers(),
        authorise=authorise, audit=app.state.audit, verifier=verifier,
        descriptions=POPULATION_DESCRIPTIONS)
    app.state.executor = executor
    mount_tools(app, executor)
    descriptors = {n: service_tool_descriptor(n, POPULATION_DESCRIPTIONS[n], a,
                                              c.POPULATION_TOOL_RESPONSES[n])
                   for n, a in c.POPULATION_TOOL_ARGS.items()}
    mount_mcp(app, "/mcp/population", McpMount("population", executor,
                                               list(c.POPULATION_TOOL_ARGS), descriptors))
    mount_a2a(app, settings.services.population, "ahdt-orchestrator-population",
              "Orchestrator of the Population twin", ORCHESTRATOR_SKILLS, _skill,
              version="1.0.0")
    return app


async def _skill(skill: str, args: Mapping[str, Any]) -> dict[str, Any]:
    from ahdt.registry import load_registry
    from atra.connectors import DTKind

    twin = load_registry().get(DTKind.POPULATION)
    goals = [g.model_dump(mode="json") for g in twin.standing_goals] if twin else []
    if skill == "get_goals":
        return {"twin": "population", "goals": goals}
    return {"twin": "population", "met": [g["id"] for g in goals], "unmet": []}
