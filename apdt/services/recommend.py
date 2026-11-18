"""Recommendations for an episode from the clinical reasoner, each with its explanation bundle.

One run of the reasoner gives up to four recommendations: the working diagnosis, the next
tests by value of information, the first eligible treatment option with its safety issues, and
the care plan that delivers it. A repeated request with unchanged inputs returns the stored
recommendations.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import asdict
from typing import Any

from apdt.models.context import Observations, Patient
from apdt.models.reasoning import Assessment, ClinicalReasoner
from apdt.models.registry import BY_ID
from apdt.models.treatment.options import Option
from apdt.services.ahdt_access import AHDTAccess, Missing
from apdt.services.inputs import from_resources
from apdt.services.journal import Journal
from apdt.services.memory_store import InMemoryEpisodeStore
from apdt.xai.bundle import Kind, build_bundle
from atra import contracts as c
from atra.backends.base import ModelRegistryBackend
from atra.codes import code
from atra.gateway import CallContext

AGENTS: dict[str, str] = {
    "diagnosis": "differential-diagnosis-agent", "test": "investigation-agent",
    "treatment": "treatment-planning-agent", "care": "care-coordination-agent"}
AUTONOMY: dict[str, c.AutonomyLevel] = {
    "diagnosis": c.AutonomyLevel.RECOMMEND, "test": c.AutonomyLevel.PREPARE_FOR_SIGNATURE,
    "treatment": c.AutonomyLevel.PREPARE_FOR_SIGNATURE, "care": c.AutonomyLevel.RECOMMEND}
MODELS: dict[str, tuple[str, ...]] = {
    "diagnosis": ("apdt.diagnosis.differential_bn", "apdt.diagnosis.neuro_symbolic",
                  "apdt.diagnosis.result_interpretation"),
    "test": ("apdt.diagnosis.differential_bn", "apdt.diagnosis.test_selection"),
    "treatment": ("apdt.treatment.options", "apdt.treatment.dosing", "apdt.treatment.safety"),
    "care": ("apdt.treatment.options", "apdt.care.early_warning")}
DIFFERENTIAL_SHOWN = 5
TESTS_SHOWN = 5
SIMULATION_HORIZON_H = 72
type Proposed = Callable[[c.Recommendation], Awaitable[None]]


class NothingToRecommend(ValueError):
    """The inputs support no candidate diagnosis."""


def _inputs_key(patient: Patient, obs: Observations) -> str:
    body = json.dumps([asdict(patient), asdict(obs)], sort_keys=True, default=str)
    return hashlib.sha256(body.encode()).hexdigest()


def _numeric_mg(option: Option) -> tuple[float, str, str] | None:
    """(mg, atc, name) of the first dose with a numeric milligram amount and an ATC code."""
    for dose in option.doses:
        mg = dose.per_dose.get("mg")
        if isinstance(mg, dict) and mg:
            first = next(iter(mg))
            mg_value, label = mg[first], f"{dose.drug} (the {first} component)"
        else:
            mg_value, label = mg, dose.drug
        if dose.atc and isinstance(mg_value, int | float):
            return float(mg_value), dose.atc, label
    return None


def _number(value: Any, default: float) -> float:
    """A scalar from a kb value that is a number or a range `[low, high]` (the low end)."""
    if isinstance(value, list):
        value = value[0] if value else default
    return float(value) if isinstance(value, int | float) else default


def _schedule_h(option: Option) -> list[float]:
    sched = option.doses[0].schedule if option.doses else {}
    if "every_h" in sched:
        step = _number(sched["every_h"], 24.0)
    else:
        step = 24.0 / _number(sched.get("doses_per_day"), 1.0)
    days = _number(sched.get("duration_days", sched.get("total_duration_days")), 3.0)
    end = min(days * 24.0, float(SIMULATION_HORIZON_H))
    out, t = [], 0.0
    while t < end:
        out.append(round(t, 2))
        t += step
    return out


def scenario_of(option: Option) -> tuple[dict[str, Any], list[str]]:
    """The AHDT scenario for an option and the assumptions that state how it was built."""
    twins = ["renal_urinary", "hepatobiliary", "whole_body"]
    found = _numeric_mg(option)
    if found is None:
        return ({"kind": "intervention", "intervention": {"option_id": option.option_id},
                 "dts": twins},
                [f"{option.option_id} has no single milligram dose, so the run shows the "
                 "course without a drug effect."])
    mg, atc, label = found
    route = option.doses[0].schedule.get("route", "oral")
    route = route if isinstance(route, str) else str(route[0])
    return ({"kind": "drug", "drug": {"atc": atc, "dose_mg": mg, "route": route,
                                      "schedule_h": _schedule_h(option)}, "dts": twins},
            [f"Dose and schedule come from the knowledge base ({option.option_id}): "
             f"{mg:g} mg of {label}, {route}."])


class Recommender:
    def __init__(self, store: InMemoryEpisodeStore, ahdt: AHDTAccess,
                 models: ModelRegistryBackend, journal: Journal,
                 on_proposed: Proposed | None = None) -> None:
        self.store = store
        self.ahdt = ahdt
        self.models = models
        self.journal = journal
        self.on_proposed = on_proposed
        self._reasoner: ClinicalReasoner | None = None
        self._lock = asyncio.Lock()

    def reasoner(self) -> ClinicalReasoner:
        if self._reasoner is None:
            self._reasoner = ClinicalReasoner()
        return self._reasoner

    async def _versions(self, kind: str, with_ews: bool) -> list[c.ModelRef]:
        refs = []
        for model_id in MODELS[kind]:
            if model_id == "apdt.care.early_warning" and not with_ews:
                continue
            try:
                entry = await self.models.get(model_id)
            except KeyError:
                await self.models.register(BY_ID[model_id].entry())
                entry = await self.models.get(model_id)
            refs.append(c.ModelRef(model_id=entry.model_id, version=entry.version))
        return refs

    async def for_episode(self, ep: c.Episode, ctx: CallContext) -> list[c.Recommendation]:
        async with self._lock:
            patient, obs = from_resources(self.store.resources[ep.episode_id], ep.tenant_id)
            key = _inputs_key(patient, obs)
            if self.store.input_keys.get(ep.episode_id) == key \
                    and self.store.recommendations[ep.episode_id]:
                return list(self.store.recommendations[ep.episode_id])
            reasoner = self.reasoner()
            a = await asyncio.to_thread(reasoner.assess, patient, obs, hdt_id=ep.hdt_id)
            if a.differential.top() is None:
                raise NothingToRecommend("the recorded findings support no diagnosis")
            fresh = await self._build(ep, ctx, reasoner, a)
            kept = [r for r in self.store.recommendations[ep.episode_id]
                    if r.status != "proposed"]
            self.store.recommendations[ep.episode_id] = kept + [r for r, _ in fresh]
            self.store.input_keys[ep.episode_id] = key
        for rec, bundle in fresh:
            self.store.bundles[bundle.bundle_id] = bundle
            await self.journal.proposed(ep.tenant_id, rec, bundle)
            if self.on_proposed:
                await self.on_proposed(rec)
        return list(self.store.recommendations[ep.episode_id])

    async def _build(self, ep: c.Episode, ctx: CallContext, reasoner: ClinicalReasoner,
                     a: Assessment) -> list[tuple[c.Recommendation, c.ExplanationBundle]]:
        option = a.first_option()
        trace: c.SimulationTrace | None = None
        if option is not None:
            scenario, assumptions = scenario_of(option)
            try:
                trace = await self.ahdt.simulate(ep.tenant_id, scenario, ctx, assumptions,
                                                 SIMULATION_HORIZON_H)
            except Missing:
                trace = None
        top = a.differential.top()
        assert top is not None
        payloads: list[tuple[Kind, dict[str, Any], float]] = [
            ("diagnosis", _diagnosis_payload(a), top.probability)]
        if a.tests:
            payloads.append(("test", _tests_payload(a), top.probability))
        if option is not None:
            cond = next((x for x in a.differential.candidates
                         if x.condition == option.condition), top)
            payloads.append(("treatment", _treatment_payload(option), cond.probability))
            payloads.append(("care", _care_payload(a, option), cond.probability))
        out = []
        for kind, payload, confidence in payloads:
            n = self.store.next_number(ep.episode_id)
            rid, bid = f"rec-{ep.episode_id}-{n}", f"bun-{ep.episode_id}-{n}"
            rec = c.Recommendation(
                recommendation_id=rid, episode_id=ep.episode_id, hdt_id=ep.hdt_id, kind=kind,
                payload=payload, confidence=round(confidence, 4), status="proposed",
                bundle_id=bid, autonomy_level=AUTONOMY[kind], created_by_agent=AGENTS[kind])
            bundle = build_bundle(
                bundle_id=bid, recommendation_id=rid, kind=kind, a=a, model=reasoner.model,
                option=option if kind in ("treatment", "care") else None,
                versions=await self._versions(kind, a.early_warning is not None), trace=trace)
            out.append((rec, bundle))
        return out


def _condition_code(condition: str, name: str) -> dict[str, Any] | None:
    from apdt.models.context import kb

    snomed = kb().entry(condition).content().get("snomed")
    return code("snomed", str(snomed), name).model_dump() if snomed else None


def _diagnosis_payload(a: Assessment) -> dict[str, Any]:
    top = a.differential.top()
    assert top is not None
    listing = a.listing
    return {"code": _condition_code(top.condition, top.name),
            "condition": top.condition, "name": top.name,
            "probability": round(top.probability, 4),
            "differential": [{"condition": x.condition, "name": x.name,
                              "code": _condition_code(x.condition, x.name),
                              "probability": round(x.probability, 4)}
                             for x in a.differential.candidates[:DIFFERENTIAL_SHOWN]],
            "excluded": [{"condition": x.condition, "reason": x.reason}
                         for x in (listing.excluded if listing else [])],
            "must_rule_out": [{"condition": x.condition, "name": x.name,
                               "red_flags": list(x.red_flags)}
                              for x in (listing.must_rule_out if listing else [])]}


def _tests_payload(a: Assessment) -> dict[str, Any]:
    return {"tests": [{"test_id": t.test_id, "name": t.name, "voi": round(t.voi, 4),
                       "score": round(t.score, 4), "cost_ngn": t.cost_ngn,
                       "turnaround_h": t.turnaround_h, "on_site": t.on_site,
                       "p_positive": round(t.p_positive, 4),
                       "top_if_positive": t.top_if_positive, "top_if_negative": t.top_if_negative}
                      for t in a.tests[:TESTS_SHOWN]]}


def _dose_payload(option: Option) -> list[dict[str, Any]]:
    return [{"dose_id": d.dose_id, "drug": d.drug, "atc": d.atc, "per_dose": d.per_dose,
             "schedule": d.schedule, "basis": d.basis} for d in option.doses]


def _treatment_payload(option: Option) -> dict[str, Any]:
    return {"option_id": option.option_id, "condition": option.condition,
            "preference": option.preference, "note": option.note, "doses": _dose_payload(option),
            "issues": [{"check": i.check, "severity": i.severity, "ix_id": i.ix_id,
                        "summary": i.summary, "management": i.management,
                        "blocks_signing": i.blocks_signing, "detected_issue": i.detected_issue}
                       for i in option.issues],
            "blocks_signing": option.blocked, "adjustments": option.adjustments}


def _care_payload(a: Assessment, option: Option) -> dict[str, Any]:
    ews = a.early_warning
    monitoring = [d.schedule["monitoring"] for d in option.doses if "monitoring" in d.schedule]
    return {"option_id": option.option_id, "plan": _dose_payload(option),
            "monitoring": monitoring,
            "early_warning": None if ews is None else {
                "scale": ews.scale, "total": ews.total, "band": ews.band,
                "components": dict(ews.components),
                "monitoring": dict(ews.monitoring) if ews.monitoring else None}}
