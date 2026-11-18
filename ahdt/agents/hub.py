"""The agents of one AHDT app: guard, orchestrators (one per twin) and the conductor."""

from __future__ import annotations

from typing import Any

from ahdt.agents.conductor import Conductor
from ahdt.agents.guard import SafetyGuard
from ahdt.agents.orchestrator import TwinOrchestrator
from ahdt.agents.toolbox import ToolBox
from ahdt.registry import Registry
from ahdt.services import Services
from atra.connectors import DTKind


class AgentHub:
    def __init__(self, services: Services, registry: Registry) -> None:
        runtime = services.runtime
        self.registry = registry
        self.kb = runtime.kb
        self.guard = SafetyGuard(runtime.audit, runtime.consents)
        self.toolbox = ToolBox(services.handlers(), self.guard)
        self._orchestrators: dict[DTKind, TwinOrchestrator] = {}
        self.reports: dict[tuple[str, str], dict[str, Any]] = {}
        self.conductor = Conductor(self.orchestrator, self.guard, self.kb, runtime)

    def orchestrator(self, kind: DTKind) -> TwinOrchestrator | None:
        if kind not in self._orchestrators:
            definition = self.registry.get(kind)
            if definition is None or not definition.standing_goals:
                return None
            self._orchestrators[kind] = TwinOrchestrator(definition, self.toolbox, self.kb)
        return self._orchestrators[kind]
