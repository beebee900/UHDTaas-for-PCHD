"""APDT Layer 7: the 7.1 agents and the 7.2 goal orchestrators."""

from __future__ import annotations

from dataclasses import dataclass

from apdt.agents.clinical import (
    DifferentialDiagnosisAgent,
    EvidenceAssemblyAgent,
    HistoryTakingAgent,
    InvestigationAgent,
    PharmacotherapyAgent,
    TreatmentPlanningAgent,
)
from apdt.agents.guard import AutonomyDenied, SafetyConsentGuard
from apdt.services.recommend import Recommender
from atra.provenance import AuditLog

__all__ = ["AgentSet", "AutonomyDenied", "SafetyConsentGuard"]


@dataclass
class AgentSet:
    guard: SafetyConsentGuard
    history: HistoryTakingAgent
    evidence: EvidenceAssemblyAgent
    differential: DifferentialDiagnosisAgent
    investigation: InvestigationAgent
    treatment: TreatmentPlanningAgent
    pharmacotherapy: PharmacotherapyAgent

    @classmethod
    def build(cls, recommender: Recommender, audit: AuditLog) -> AgentSet:
        guard, store, ahdt = SafetyConsentGuard(audit), recommender.store, recommender.ahdt
        return cls(
            guard=guard,
            history=HistoryTakingAgent(guard, store),
            evidence=EvidenceAssemblyAgent(guard, store, ahdt),
            differential=DifferentialDiagnosisAgent(guard, store, recommender),
            investigation=InvestigationAgent(guard, store, recommender),
            treatment=TreatmentPlanningAgent(guard, store, recommender, ahdt),
            pharmacotherapy=PharmacotherapyAgent(guard, store, ahdt))
