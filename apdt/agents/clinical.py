"""The core 7.1 agents (design 05, 5.9.1). Each calls existing APDT services through the
guard and returns an `Outcome`. Gateway tools run with the delegating human's role."""

from __future__ import annotations

import asyncio
from typing import Any

from apdt.agents.base import BaseAgent, Outcome, ToolKit
from apdt.agents.guard import SafetyConsentGuard
from apdt.models.treatment.options import Option
from apdt.services.ahdt_access import AHDTAccess, Missing
from apdt.services.inputs import MissingInputs, from_resources
from apdt.services.memory_store import InMemoryEpisodeStore
from apdt.services.recommend import NothingToRecommend, Recommender, scenario_of
from atra import contracts as c
from atra.gateway import CallContext

SIMULATION_HORIZON_H = 72
EXPLAIN_AUDIENCE = "clinician"


def pending(recs: list[c.Recommendation], kind: str) -> tuple[c.Recommendation | None, str | None]:
    """The newest undecided recommendation of `kind`, or the reason there is none."""
    wanted = [r for r in recs if r.kind == kind]
    open_ = [r for r in wanted if r.status == "proposed"]
    if open_:
        return open_[-1], None
    return None, (f"the {kind} recommendation has been decided already" if wanted
                  else f"the reasoner produced no {kind} recommendation")


class HistoryTakingAgent(BaseAgent):
    """Lists the inputs that the episode lacks. It asks no questions."""
    name = "history-taking-agent"
    tools = frozenset({"apdt.episode.read"})
    actions = frozenset({"show_data"})
    autonomy = c.AutonomyLevel.INFORM

    async def run(self, ep: c.Episode, ctx: CallContext, goal_id: str) -> Outcome:
        kit = self.kit(ep, ctx)

        async def gaps() -> list[str]:
            try:
                _, obs = from_resources(self.store.resources[ep.episode_id], ep.tenant_id)
            except MissingInputs as exc:
                return exc.missing
            return [] if (obs.findings or obs.tests or obs.measurements) else ["findings"]

        missing = await kit.use("apdt.episode.read", "show_data", {"episode": ep.episode_id},
                                gaps)
        return self.outcome(goal_id, kit, {"missing_inputs": missing})


class EvidenceAssemblyAgent(BaseAgent):
    name = "evidence-assembly-agent"
    tools = frozenset({"apdt.episode.read", "ahdt.data.observations", "ahdt.data.medications",
                       "ahdt.model.state", "ahdt.xai.explain"})
    actions = frozenset({"show_data"})
    autonomy = c.AutonomyLevel.INFORM

    def __init__(self, guard: SafetyConsentGuard, store: InMemoryEpisodeStore,
                 ahdt: AHDTAccess) -> None:
        super().__init__(guard, store)
        self.ahdt = ahdt

    async def run(self, ep: c.Episode, ctx: CallContext, goal_id: str) -> Outcome:
        kit = self.kit(ep, ctx)
        vitals = await kit.optional(
            "ahdt.data.observations", "show_data", {"vitals": True},
            lambda: self.ahdt.vitals(ep.tenant_id, ctx)) or {}
        meds = await kit.optional(
            "ahdt.data.medications", "show_data", {"active_only": True},
            lambda: self.ahdt.medications(ep.tenant_id, ctx)) or []

        async def episode_facts() -> dict[str, int]:
            others = [e for e in self.store.episodes.values()
                      if e.hdt_id == ep.hdt_id and e.episode_id != ep.episode_id]
            return {"prior_episodes": len(others),
                    "recorded_items": len(self.store.resources[ep.episode_id])}

        facts = await kit.use("apdt.episode.read", "show_data", {"episode": ep.episode_id},
                              episode_facts)
        data = {"vitals": {k: v.model_dump(mode="json") for k, v in vitals.items()},
                "medications": [m.model_dump(mode="json") for m in meds], **facts}
        return self.outcome(goal_id, kit, data)

    async def explain(self, ep: c.Episode, ctx: CallContext, goal_id: str,
                      bundle: c.ExplanationBundle | None) -> Outcome:
        """The bundle's summary, and the AHDT explanation of the simulation behind it."""
        kit = self.kit(ep, ctx)
        data: dict[str, Any] = {
            "bundle_id": bundle.bundle_id if bundle else None,
            "summary": bundle.recommendation.text if bundle else None,
            "missing_parts": bundle.missing_parts() if bundle else [], "ahdt_explanation": None}
        trace = bundle.simulation_trace if bundle else None
        if trace is not None:
            args = {"output_id": trace.output_id, "audience": EXPLAIN_AUDIENCE}
            raw = await kit.optional("ahdt.xai.explain", "show_data", args,
                                     lambda: self.ahdt.call(ep.tenant_id, "ahdt.xai.explain",
                                                            args, ctx))
            if raw is not None:
                e = c.AHDTExplanation.model_validate(raw)
                data["ahdt_explanation"] = {
                    "explanation_id": e.explanation_id, "output_id": e.output_id,
                    "explainer": e.explainer, "method_family": e.method_family}
        return self.outcome(goal_id, kit, data,
                            explanations=[bundle.bundle_id] if bundle else [])


class _RecommendingAgent(BaseAgent):
    kind: str
    tool: str

    def __init__(self, guard: SafetyConsentGuard, store: InMemoryEpisodeStore,
                 recommender: Recommender) -> None:
        super().__init__(guard, store)
        self.recommender = recommender

    async def _recommend(self, kit: ToolKit, ep: c.Episode, ctx: CallContext,
                         action: str) -> list[c.Recommendation] | str:
        try:
            return await kit.use(self.tool, action, {"episode": ep.episode_id},
                                 lambda: self.recommender.for_episode(ep, ctx))
        except (MissingInputs, NothingToRecommend) as exc:
            return str(exc)

    async def run(self, ep: c.Episode, ctx: CallContext, goal_id: str) -> Outcome:
        kit = self.kit(ep, ctx)
        recs = await self._recommend(kit, ep, ctx, self.action)
        if isinstance(recs, str):
            return self.outcome(goal_id, kit, {"error": recs}, failed=True)
        rec, error = pending(recs, self.kind)
        if rec is None:
            return self.outcome(goal_id, kit, {"error": error}, failed=True)
        return self.outcome(goal_id, kit, {"recommendation_id": rec.recommendation_id,
                                           "bundle_id": rec.bundle_id}, proposals=[rec],
                            explanations=[rec.bundle_id] if rec.bundle_id else [])

    action = "recommend"


class DifferentialDiagnosisAgent(_RecommendingAgent):
    name = "differential-diagnosis-agent"
    tools = frozenset({"apdt.models.differential", "apdt.xai.bundle"})
    actions = frozenset({"recommend"})
    kind = "diagnosis"
    tool = "apdt.models.differential"


class InvestigationAgent(_RecommendingAgent):
    name = "investigation-agent"
    tools = frozenset({"apdt.models.test_selection"})
    actions = frozenset({"recommend", "prepare_record"})
    autonomy = c.AutonomyLevel.PREPARE_FOR_SIGNATURE
    kind = "test"
    tool = "apdt.models.test_selection"
    action = "prepare_record"


class TreatmentPlanningAgent(_RecommendingAgent):
    name = "treatment-planning-agent"
    tools = frozenset({"apdt.models.options", "ahdt.model.simulate", "ahdt.model.cosimulate"})
    actions = frozenset({"recommend", "show_data"})
    autonomy = c.AutonomyLevel.PREPARE_FOR_SIGNATURE
    kind = "treatment"
    tool = "apdt.models.options"

    def __init__(self, guard: SafetyConsentGuard, store: InMemoryEpisodeStore,
                 recommender: Recommender, ahdt: AHDTAccess) -> None:
        super().__init__(guard, store, recommender)
        self.ahdt = ahdt

    async def enumerate(self, ep: c.Episode, ctx: CallContext,
                        goal_id: str) -> tuple[Outcome, list[Option]]:
        """The treatment recommendation and every eligible option for its condition."""
        outcome = await self.run(ep, ctx, goal_id)
        if outcome.result.status == "failed":
            return outcome, []
        rec = outcome.result.proposals[0]
        kit = self.kit(ep, ctx)

        async def eligible() -> list[Option]:
            patient, obs = from_resources(self.store.resources[ep.episode_id], ep.tenant_id)
            a = await asyncio.to_thread(self.recommender.reasoner().assess, patient, obs,
                                        hdt_id=ep.hdt_id, with_tests=False)
            found = a.options.get(str(rec.payload["condition"]))
            return list(found.eligible) if found else []

        options = await kit.use("apdt.models.options", "recommend",
                                {"condition": rec.payload["condition"]}, eligible)
        outcome.result.tool_calls.extend(kit.calls)
        outcome.data["options"] = [_option_view(o) for o in options]
        return outcome, options

    async def simulate_each(self, ep: c.Episode, ctx: CallContext, goal_id: str,
                            options: list[Option]) -> Outcome:
        """A forked what-if per option. A simulation the AHDT refuses is an error entry."""
        kit = self.kit(ep, ctx)
        results: list[dict[str, Any]] = []
        for option in options:
            scenario, assumptions = scenario_of(option)
            before = len(kit.missing)

            async def go(sc: dict[str, Any] = scenario, an: list[str] = assumptions
                         ) -> c.SimulationTrace:
                try:
                    return await self.ahdt.simulate(ep.tenant_id, sc, ctx, an,
                                                    SIMULATION_HORIZON_H)
                except ValueError as exc:
                    raise Missing("ahdt.model.simulate", f"invalid result ({exc})") from exc

            trace = await kit.optional("ahdt.model.simulate", "recommend",
                                       {"option_id": option.option_id, "scenario": scenario}, go)
            error = kit.missing[-1] if len(kit.missing) > before else None
            results.append({"option_id": option.option_id, "error": error,
                            "simulation": trace.model_dump(mode="json") if trace else None})
        return self.outcome(goal_id, kit, {"simulations": results})


class PharmacotherapyAgent(BaseAgent):
    name = "pharmacotherapy-agent"
    tools = frozenset({"apdt.models.safety", "ahdt.data.medications", "ahdt.data.genome",
                       "ahdt.model.facet", "ahdt.model.simulate"})
    actions = frozenset({"recommend", "show_data"})

    def __init__(self, guard: SafetyConsentGuard, store: InMemoryEpisodeStore,
                 ahdt: AHDTAccess) -> None:
        super().__init__(guard, store)
        self.ahdt = ahdt

    async def check(self, ep: c.Episode, ctx: CallContext, goal_id: str,
                    options: list[Option]) -> Outcome:
        """Dose, interaction and allergy findings per option, and the active medications."""
        kit = self.kit(ep, ctx)
        meds = await kit.optional(
            "ahdt.data.medications", "show_data", {"active_only": True},
            lambda: self.ahdt.medications(ep.tenant_id, ctx)) or []

        async def checks() -> list[dict[str, Any]]:
            return [{"option_id": o.option_id, "blocks_signing": o.blocked,
                     "adjustments": len(o.adjustments),
                     "issues": [{"check": i.check, "severity": i.severity,
                                 "summary": i.summary, "blocks_signing": i.blocks_signing}
                                for i in o.issues]} for o in options]

        rows = await kit.use("apdt.models.safety", "recommend",
                             {"options": [o.option_id for o in options]}, checks)
        return self.outcome(goal_id, kit, {
            "checks": rows, "active_medications": [m.label for m in meds]})


def _option_view(option: Option) -> dict[str, Any]:
    return {"option_id": option.option_id, "preference": option.preference,
            "note": option.note, "blocks_signing": option.blocked}
