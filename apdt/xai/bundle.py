"""Explanation bundles (design 05, 5.6): the parts that the core reasoning chain supports.

Evidence comes from the Bayesian network's per-item log-likelihood ratios, alternatives from
the ranked differential or the option set, counterfactuals from re-scoring the differential
with one more or one changed result, and citations from the kb entry that produced the
recommendation. The patient summary is a fixed template.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Literal

from apdt.knowledge.sources import load_sources
from apdt.models.context import kb
from apdt.models.diagnosis.bn import Candidate, Differential, DifferentialModel, Item
from apdt.models.reasoning import Assessment
from apdt.models.treatment.options import Option
from atra import contracts as c
from atra.codes import code

type Kind = Literal["diagnosis", "test", "treatment", "care"]
MAX_ALTERNATIVES = 4
MAX_COUNTERFACTUALS = 4
AUDIENCES = ("medical_officer", "pharmacist", "nurse", "patient")


def _name(entry_id: str) -> str:
    return str(kb().entry(entry_id).content().get("name", entry_id))


def _evidence(items: tuple[Item, ...]) -> list[c.EvidenceItem]:
    out = []
    for it in items:
        is_test = it.node_id.startswith("test.")
        state = ("positive" if it.value else "negative") if is_test else \
            ("present" if it.value else "absent")
        out.append(c.EvidenceItem(source="apdt", item=f"{_name(it.node_id)}: {state}",
                                  value=it.value, weight=round(it.log_lr, 3)))
    return out


def citations_of(entry_ids: list[str]) -> list[c.Citation]:
    """Citations of the given kb entries, with the source title and the cited section."""
    sources = load_sources()
    out: list[c.Citation] = []
    for entry_id in entry_ids:
        for cite in kb().entry(entry_id).provenance.citations():
            src = sources.get(cite.source)
            section = cite.section or (f"p. {cite.page}" if cite.page else "provenance")
            out.append(c.Citation(
                kb_entry_id=entry_id, source_title=src.title if src else cite.source,
                section=section, url=(src.landing or src.url) if src else None))
    return out


def _candidate(diff: Differential, condition: str) -> Candidate | None:
    return next((x for x in diff.candidates if x.condition == condition), None)


def _alternatives_from_differential(diff: Differential, chosen: str) -> list[c.Alternative]:
    top = _candidate(diff, chosen)
    out = []
    for cand in diff.candidates:
        if cand.condition == chosen:
            continue
        lacking = [_name(i.node_id) for i in (top.for_ if top else ())
                   if i.node_id not in {j.node_id for j in cand.for_}]
        reason = (f"Not supported by {', '.join(lacking[:3])}." if lacking
                  else "Less of the recorded evidence supports it.")
        out.append(c.Alternative(
            text=cand.name, score=round(cand.probability, 4),
            why_lower=f"Probability {cand.probability:.0%} against "
                      f"{top.probability:.0%}. {reason}" if top else reason))
        if len(out) == MAX_ALTERNATIVES:
            break
    return out


def _alternatives_from_options(a: Assessment, option: Option) -> list[c.Alternative]:
    option_set = a.options[option.condition]
    cand = _candidate(a.differential, option.condition)
    p = round(cand.probability, 4) if cand else 0.0
    out = [c.Alternative(text=_option_text(o), score=p,
                         why_lower=f"A {o.preference.replace('_', ' ')} option; "
                                   f"the chosen one is {option.preference.replace('_', ' ')}.")
           for o in option_set.eligible if o.option_id != option.option_id]
    out += [c.Alternative(text=i.option_id.split(".", 1)[1].replace(".", " ").replace("_", " "),
                          score=0.0, why_lower=i.reason or "Not eligible for this patient.")
            for i in option_set.ineligible]
    return out[:MAX_ALTERNATIVES]


def _option_text(option: Option) -> str:
    drugs = [d.drug for d in option.doses]
    return " + ".join(dict.fromkeys(drugs)) if drugs else option.option_id


def _with_result(model: DifferentialModel, a: Assessment, key: str, kind: str, value: bool
                 ) -> tuple[str, float, float]:
    """(name of the new top, its new probability, its current probability) after one result."""
    obs = replace(a.observations, findings=dict(a.observations.findings),
                  tests=dict(a.observations.tests))
    (obs.tests if kind == "test" else obs.findings)[key] = value
    diff = model.differential(a.patient, obs)
    top = diff.top()
    if top is None:
        return "No listed condition is supported", 0.0, 0.0
    return top.name, top.probability, a.differential.marginals.get(top.condition, 0.0)


def counterfactuals(model: DifferentialModel, a: Assessment) -> list[c.BundleCounterfactual]:
    """Results that would change the top diagnosis, then a negative result of the best tests,
    then the removal of the strongest supporting finding. `delta` is the rise in the probability
    of the new top diagnosis."""
    now = a.differential.top()
    out: list[c.BundleCounterfactual] = []
    seen: set[tuple[str, bool]] = set()

    def add(key: str, kind: str, value: bool) -> None:
        if (key, value) in seen or len(out) >= MAX_COUNTERFACTUALS:
            return
        seen.add((key, value))
        new_top, new_p, old_p = _with_result(model, a, key, kind, value)
        label = _name(key)
        state = ("positive" if value else "negative") if kind == "test" else \
            ("present" if value else "absent")
        out.append(c.BundleCounterfactual(change=f"{label} {state}", new_top=new_top,
                                          delta=round(new_p - old_p, 4)))

    for m in a.mind_changes:
        add(m.test_id, "test", m.result)
    for t in a.tests[:2]:
        add(t.test_id, "test", False)
    if now is not None and not out:
        strongest = max(now.for_, key=lambda i: i.log_lr, default=None)
        if strongest is not None:
            kind = "test" if strongest.node_id.startswith("test.") else "finding"
            add(strongest.node_id, kind, False)
    return out


def patient_summary(kind: Kind, a: Assessment, option: Option | None) -> str:
    top = a.differential.top()
    if kind == "diagnosis" and top is not None:
        others = len(a.differential.candidates) - 1
        return (f"Your symptoms and tests point most strongly to {top.name}. "
                f"{others} other possible cause{'s were' if others != 1 else ' was'} also "
                "checked. Your clinician will go through this with you and confirm it.")
    if kind == "test" and a.tests:
        t = a.tests[0]
        where = "at this facility" if t.on_site else "at another site"
        return (f"To be more certain, the next suggested test is {t.name}. It is done {where}, "
                f"costs about {t.cost_ngn:,.0f} naira and takes about {t.turnaround_h:g} "
                "hours. Your clinician decides whether to order it.")
    if option is not None:
        drugs = _option_text(option)
        checks = len(option.issues)
        safety = (f" Your pharmacist will check {checks} medicine safety point"
                  f"{'s' if checks != 1 else ''} before you start." if checks else "")
        if kind == "care":
            return (f"Your care plan follows the treatment {drugs}. Your care team will check "
                    "on you at regular times. Tell the nurse at once if you feel worse."
                    + safety)
        return (f"The suggested treatment is {drugs}. Your clinician and pharmacist must "
                "approve it before you receive it." + safety)
    return "Your care team has reviewed your record and will talk to you about the next step."


def audience_views(kind: Kind, option: Option | None) -> dict[str, dict[str, Any]]:
    views: dict[str, dict[str, Any]] = {
        "medical_officer": {"parts": "all"},
        "nurse": {"parts": ["recommendation", "evidence", "patient_summary"]},
        "patient": {"parts": ["patient_summary"]}}
    pharm: dict[str, Any] = {"parts": ["recommendation", "citations", "alternatives"]}
    if option is not None:
        pharm["issues"] = [i.summary for i in option.issues]
        pharm["doses"] = [{"drug": d.drug, "atc": d.atc, "per_dose": d.per_dose,
                           "schedule": d.schedule} for d in option.doses]
    views["pharmacist"] = pharm
    return views


def view_for(bundle: c.ExplanationBundle, audience: str) -> c.ExplanationBundle:
    """The bundle with only the parts that `audience` may see."""
    parts = {str(k): v for k, v in bundle.audience_views.items()}[audience]["parts"]
    if parts == "all":
        return bundle
    keep = set(parts) | {"recommendation"}
    return bundle.model_copy(update={
        "evidence_for": bundle.evidence_for if "evidence" in keep else [],
        "evidence_against": bundle.evidence_against if "evidence" in keep else [],
        "citations": bundle.citations if "citations" in keep else [],
        "counterfactuals": [],
        "simulation_trace": None,
        "alternatives": bundle.alternatives if "alternatives" in keep else []})


def build_bundle(*, bundle_id: str, recommendation_id: str, kind: Kind, a: Assessment,
                 model: DifferentialModel, option: Option | None,
                 versions: list[c.ModelRef], trace: c.SimulationTrace | None,
                 created_at: datetime | None = None) -> c.ExplanationBundle:
    """The bundle of one recommendation. `option` is the chosen treatment option."""
    diff = a.differential
    top = diff.top()
    if top is None:
        raise ValueError("the differential is empty")
    cand = _candidate(diff, option.condition) if option is not None else top
    cand = cand or top
    cond_entry = kb().entry(cand.condition).content()
    if kind == "test":
        t = a.tests[0]
        rec = c.BundleRecommendation(
            text=f"Order {t.name}", confidence=round(top.probability, 4),
            code=code("loinc", str(kb().entry(t.test_id).content()["loinc"]), t.name)
            if "loinc" in kb().entry(t.test_id).content() else None)
        cites = citations_of([t.test_id])
        alternatives = [c.Alternative(text=x.name, score=round(x.voi, 4),
                                      why_lower=f"Lower value per cost: score {x.score:.3g} "
                                                f"against {t.score:.3g}.")
                        for x in a.tests[1:1 + MAX_ALTERNATIVES]]
    elif kind == "diagnosis":
        rec = c.BundleRecommendation(
            text=cand.name, confidence=round(cand.probability, 4),
            code=code("snomed", str(cond_entry["snomed"]), cand.name)
            if "snomed" in cond_entry else None)
        cites = citations_of([cand.condition])
        alternatives = _alternatives_from_differential(diff, cand.condition)
    else:
        assert option is not None
        rec = c.BundleRecommendation(
            text=_option_text(option), confidence=round(cand.probability, 4),
            code=code("atc", option.doses[0].atc, option.doses[0].drug)
            if option.doses and option.doses[0].atc else None)
        cites = citations_of([option.option_id])
        alternatives = _alternatives_from_options(a, option)
    if not alternatives:
        alternatives = _alternatives_from_differential(diff, cand.condition)
    if kind == "test" and not alternatives:
        alternatives = _alternatives_from_differential(diff, top.condition)
    return c.ExplanationBundle(
        bundle_id=bundle_id, recommendation_id=recommendation_id, recommendation=rec,
        evidence_for=_evidence(cand.for_), evidence_against=_evidence(cand.against),
        citations=cites, counterfactuals=counterfactuals(model, a), simulation_trace=trace,
        alternatives=alternatives,
        patient_summary=c.PatientSummary(language="en", text=patient_summary(kind, a, option)),
        audience_views=audience_views(kind, option),
        created_at=created_at or datetime.now(UTC), model_versions=versions)

