"""Goal runs (design 05, 5.9.2). Diagnosis and treatment runs are LangGraph agent graphs.
The care run calls the reasoner and waits at one interrupt for the accountable role. A
decision on an interrupt changes the recommendation's status.

Agents propose and clinicians decide: a decision made by an agent or a service identity is
refused and audited.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from apdt.agents import AgentSet
from apdt.agents.diagnosis import DiagnosisOrchestrator
from apdt.agents.orchestrator import GoalOrchestrator
from apdt.agents.treatment import TreatmentOrchestrator
from apdt.services.inputs import MissingInputs
from apdt.services.journal import Journal
from apdt.services.memory_store import InMemoryEpisodeStore
from apdt.services.recommend import AGENTS, NothingToRecommend, Recommender
from atra import contracts as c
from atra.gateway import CallContext
from atra.ids import uuid7
from atra.provenance import AuditLog
from atra.service import Identity, Problem

# goal -> (interrupt kind, accountable role, allowed decisions, recommendation kind)
GOALS: Mapping[str, tuple[str, c.Role, list[str], str]] = {
    "diagnosis": ("accept_diagnosis", c.Role.MEDICAL_OFFICER,
                  ["accept", "edit", "reject", "sign"], "diagnosis"),
    "treatment": ("verify_prescription", c.Role.PHARMACIST, ["verify", "query", "reject"],
                  "treatment"),
    "care": ("approve_care_plan", c.Role.MEDICAL_OFFICER,
             ["accept", "edit", "reject", "sign"], "care")}
STATUS_OF: Mapping[str, str] = {"accept": "accepted", "verify": "accepted", "edit": "edited",
                                "reject": "overridden", "sign": "signed",
                                "decline": "declined"}
type Publish = Callable[[str, Mapping[str, Any], c.Episode | None], Awaitable[None]]
type WriteBack = Callable[[c.Recommendation, c.ClinicalDecision, c.Episode], Awaitable[None]]


def is_agent(decision: c.ClinicalDecision, ident: Identity) -> bool:
    """True when the decider is an agent or a service acting without a human session."""
    agent_ids = set(AGENTS.values())
    return (ident.delegated or ident.claims.is_service or decision.decided_by.id in agent_ids
            or decision.decided_by.id.endswith("-agent"))


class RunService:
    def __init__(self, store: InMemoryEpisodeStore, recommender: Recommender, journal: Journal,
                 audit: AuditLog, publish: Publish, write_back: WriteBack | None = None) -> None:
        self.store = store
        self.recommender = recommender
        self.journal = journal
        self.audit = audit
        self.publish = publish
        self.write_back = write_back
        self.runs: dict[str, c.RunStatus] = {}
        self.agents = AgentSet.build(recommender, audit)
        self.orchestrators: dict[str, GoalOrchestrator] = {
            "diagnosis": DiagnosisOrchestrator(self.agents, store, self.record),
            "treatment": TreatmentOrchestrator(self.agents, store, self.record)}
        self.graph_of: dict[str, GoalOrchestrator] = {}

    async def start(self, goal: str, ep: c.Episode, ctx: CallContext) -> c.RunStarted:
        run_id = f"run-{uuid7()}"
        orchestrator = self.orchestrators.get(goal)
        if orchestrator is not None:
            self.graph_of[run_id] = orchestrator
            self.runs[run_id] = await orchestrator.start(run_id, ep, ctx)
            return c.RunStarted(run_id=run_id, goal=goal)
        kind, role, allowed, rec_kind = GOALS[goal]
        try:
            recs = await self.recommender.for_episode(ep, ctx)
        except (MissingInputs, NothingToRecommend) as exc:
            self.runs[run_id] = c.RunStatus(run_id=run_id, status="failed",
                                            result={"error": str(exc)})
            return c.RunStarted(run_id=run_id, goal=goal)
        wanted = [r for r in recs if r.kind == rec_kind]
        pending = [r for r in wanted if r.status == "proposed"]
        if not pending:
            error = (f"the {rec_kind} recommendation has been decided already" if wanted
                     else f"the reasoner produced no {rec_kind} recommendation")
            self.runs[run_id] = c.RunStatus(run_id=run_id, status="failed",
                                            result={"error": error})
        else:
            rec = pending[-1]
            bundle = self.store.bundles.get(rec.bundle_id or "")
            payload: dict[str, Any] = {
                "recommendation_id": rec.recommendation_id, "bundle_id": rec.bundle_id,
                "episode_id": ep.episode_id,
                "summary": bundle.recommendation.text if bundle else None,
                "blocks_signing": bool(rec.payload.get("blocks_signing", False))}
            self.runs[run_id] = c.RunStatus(
                run_id=run_id, status="waiting_for_human",
                interrupt=c.Interrupt(kind=kind, payload=payload,
                                      allowed_decisions=allowed, required_role=role))
        return c.RunStarted(run_id=run_id, goal=goal)

    def refuse(self, ident: Identity, tenant_id: str, rec: c.Recommendation | None,
               decision: c.ClinicalDecision, reason: str, status: int = 403) -> Problem:
        self.audit.append(
            actor={"id": ident.ctx.actor_id, "role": ident.ctx.actor_role.value},
            tenant_id=tenant_id, hdt_id=rec.hdt_id if rec else None,
            episode_id=rec.episode_id if rec else None, action=f"decision.{decision.decision}",
            target=decision.recommendation_id, purpose=ident.ctx.purpose, outcome="denied",
            reason=reason)
        return Problem(status, "forbidden" if status == 403 else "invalid-request", reason)

    async def resume(self, run_id: str, decision: c.ClinicalDecision, ident: Identity,
                     tenant_id: str) -> c.RunStatus:
        run = self.runs.get(run_id)
        if run is None:
            raise Problem(404, "not-found", f"no run {run_id}")
        interrupt = run.interrupt
        rec_id = str(interrupt.payload["recommendation_id"]) if interrupt else None
        rec = self.store.recommendation(rec_id) if rec_id else None
        if is_agent(decision, ident):
            raise self.refuse(ident, tenant_id, rec, decision,
                              "a decision needs an accountable clinician, not an agent")
        if interrupt is None:
            raise Problem(409, "conflict", f"run {run_id} is not waiting for a decision")
        assert rec is not None
        if ident.ctx.actor_role != interrupt.required_role:
            raise self.refuse(ident, tenant_id, rec, decision,
                              f"this decision needs a {interrupt.required_role.value}")
        if decision.decided_by.role != ident.ctx.actor_role:
            raise self.refuse(ident, tenant_id, rec, decision,
                              "the decider's role is not the role of the signed-in user")
        if decision.recommendation_id != rec.recommendation_id:
            raise self.refuse(ident, tenant_id, rec, decision,
                              f"the run waits on {rec.recommendation_id}", status=422)
        if decision.decision not in interrupt.allowed_decisions:
            raise self.refuse(ident, tenant_id, rec, decision,
                              f"allowed decisions: {', '.join(interrupt.allowed_decisions)}",
                              status=422)
        if decision.decision in ("edit", "reject") and not decision.override_reason:
            raise self.refuse(ident, tenant_id, rec, decision,
                              "an override needs a reason", status=422)
        if decision.decision == "edit" and not decision.edited_payload:
            raise self.refuse(ident, tenant_id, rec, decision,
                              "an edit needs the edited payload", status=422)
        if decision.decision == "sign" and rec.payload.get("blocks_signing"):
            raise self.refuse(ident, tenant_id, rec, decision,
                              "a high-severity safety issue blocks signing", status=422)
        if decision.decision == "sign" and decision.signed_at is None:
            decision = decision.model_copy(update={"signed_at": datetime.now(UTC)})
        ep = self.store.get(tenant_id, rec.episode_id or "")
        orchestrator = self.graph_of.get(run_id)
        if orchestrator is not None:
            ctx = CallContext(ep.hdt_id, ident.ctx.actor_role, ident.ctx.actor_id,
                              ident.ctx.purpose, ep.episode_id, ident.ctx.agent)
            self.runs[run_id] = await orchestrator.resume(run_id, decision, ep, ctx)
            return self.runs[run_id]
        updated = await self.record(tenant_id, rec.recommendation_id, decision, True)
        done = run.model_copy(update={"status": "done", "interrupt": None, "result": {
            "decision": decision.decision, "recommendation_id": rec.recommendation_id,
            "status": updated.status}})
        self.runs[run_id] = done
        return done

    async def record(self, tenant_id: str, recommendation_id: str,
                     decision: c.ClinicalDecision, set_status: bool) -> c.Recommendation:
        """Stores a decision: it changes the status when `set_status`, is journaled, is
        published and, for a confirmed diagnosis, is written back to the AHDT."""
        rec = self.store.recommendation(recommendation_id)
        updated = self._apply(rec, decision) if set_status else rec
        ep = self.store.get(tenant_id, rec.episode_id or "")
        self.store.decisions.setdefault(ep.episode_id, []).append(decision)
        await self.journal.decided(tenant_id, decision, episode_id=ep.episode_id,
                                   hdt_id=ep.hdt_id)
        await self.publish("decision.recorded", decision.model_dump(mode="json"), ep)
        if set_status and self.write_back is not None:
            await self.write_back(updated, decision, ep)
        return updated

    def _apply(self, rec: c.Recommendation, decision: c.ClinicalDecision) -> c.Recommendation:
        changes: dict[str, Any] = {}
        status = STATUS_OF.get(decision.decision)
        if status:
            changes["status"] = status
        if decision.decision == "edit" and decision.edited_payload:
            changes["payload"] = {**rec.payload, **decision.edited_payload}
        updated = rec.model_copy(update=changes)
        self.store.replace_recommendation(updated)
        return updated
