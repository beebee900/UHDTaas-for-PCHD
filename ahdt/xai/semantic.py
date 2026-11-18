"""Explainers for rule-based, ontology and language models (design 04, 4.6.1).

- `rule_trace` lists the rules that fired for the early-warning and pharmacogenomic models,
  each with the knowledge-base entry that holds its numbers.
- `reference_trace` explains a T3 reference-state variable by its range and couplings.
- `hermit_justification` finds the axioms an ontology conclusion needs by asking HermiT
  again with each axiom removed.
- `citation_trace` and `self_consistency` explain language-model answers.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from itertools import combinations
from typing import Any

import owlready2 as owl

from ahdt.knowledge import owl as ontology
from ahdt.models.reference import default_kb
from ahdt.registry import load_registry
from ahdt.xai.subjects import ReferenceSubject, RuleSubject, TextSubject
from ahdt.xai.types import Result, driver
from atra.connectors import DTKind

HERMIT_JAVA_MB = 600


# ---------------------------------------------------------------------------
# Rule traces
# ---------------------------------------------------------------------------

def _news2_step(name: str, value: float, bands: Sequence[Mapping[str, Any]], entry: str
                ) -> dict[str, Any]:
    for band in bands:
        if "upto" not in band or value <= float(band["upto"]):
            limit = band.get("upto")
            rule = f"{name} <= {limit}" if limit is not None else f"{name} above the last limit"
            return {"rule": rule,
                    "input": name, "value": value, "score": int(band["score"]), "kb": entry}
    raise ValueError(f"no band for {name}")


def _early_warning(s: RuleSubject) -> Result:
    kb = default_kb()
    out = s.model.evaluate({}, {}, s.inputs)
    steps: list[dict[str, Any]] = []
    drivers = []
    if "news2" in out:
        table = kb.entry("news2.scoring").content()
        u = s.inputs
        on_oxygen = bool(u.get("on_oxygen", False))
        spo2_key = ("spo2_scale1" if u.get("spo2_scale") != 2 else
                    "spo2_scale2_oxygen" if on_oxygen else "spo2_scale2_air")
        for name, key in (("respiration_rate", "respiration_rate"), ("spo2", spo2_key),
                          ("systolic_bp", "systolic_bp"), ("pulse", "pulse"),
                          ("temperature", "temperature")):
            step = _news2_step(name, float(u[name]), table[key], f"news2.scoring.{key}")
            steps.append(step)
            drivers.append(driver(name, step["value"], float(step["score"])))
        cons = int(table["consciousness"][str(u["consciousness"])])
        steps.append({"rule": f"consciousness {u['consciousness']}", "input": "consciousness",
                      "value": u["consciousness"], "score": cons,
                      "kb": "news2.scoring.consciousness"})
        drivers.append(driver("consciousness", u["consciousness"], float(cons)))
        oxygen = int(table["supplemental_oxygen"]["oxygen" if on_oxygen else "air"])
        steps.append({"rule": "supplemental oxygen" if on_oxygen else "room air",
                      "input": "on_oxygen", "value": on_oxygen, "score": oxygen,
                      "kb": "news2.scoring.supplemental_oxygen"})
        drivers.append(driver("supplemental_oxygen", on_oxygen, float(oxygen)))
        steps.append({"rule": "total score and response band", "value": out["news2"],
                      "band": out["news2_band"], "kb": "news2.bands"})
        total = float(out["news2"])
    else:
        total = float(out.get("pews", math.nan))
        for key, value in out.items():
            if key.startswith("pews_") and key != "pews_level":
                steps.append({"rule": key, "score": value, "kb": "pews.scoring.common"})
                drivers.append(driver(key.removeprefix("pews_"), None, float(value)))
    return Result("rules.trace@own", "rule_trace", drivers, output=total,
                  detail={"steps": steps, "outputs": {k: v for k, v in out.items()}})


def _pharmacogenomics(s: RuleSubject) -> Result:
    kb = default_kb()
    out = s.model.evaluate({}, {}, s.inputs)
    steps: list[dict[str, Any]] = []
    diplotypes = dict(s.inputs.get("diplotypes", {}))
    diplotypes.update(s.inputs.get("measured_phenotypes", {}))
    for gene, diplotype in diplotypes.items():
        found = next((p.split(":", 1)[1] for p in out["phenotypes"]
                      if p.startswith(f"{gene}:")), None)
        if found is not None:
            method = kb.entry(f"pgx.{gene}").content()["method"]
            steps.append({"rule": f"{gene} {diplotype} by {method}", "gene": gene,
                          "diplotype": diplotype, "phenotype": found, "kb": f"pgx.{gene}"})
    for rec in out["recommendations"]:
        drug, gene, phenotype, action, _ = rec.split("|", 4)
        steps.append({"rule": f"{drug}: {gene} {phenotype}", "drug": drug, "action": action,
                      "kb": f"pgx.drug.{drug}"})
    drivers = [driver(f"{st['gene']} {st['diplotype']}", st["phenotype"], 1.0)
               for st in steps if "gene" in st and "diplotype" in st]
    return Result("rules.trace@own", "rule_trace", drivers,
                  output=float(len(out["recommendations"])),
                  detail={"steps": steps, "outputs": dict(out)})


def rule_trace(s: RuleSubject) -> Result:
    """The rules that fired, in order, with the kb entry behind each."""
    model_id = s.model_id
    if model_id.endswith("early_warning"):
        return _early_warning(s)
    if model_id.endswith("pharmacogenomics"):
        return _pharmacogenomics(s)
    out = s.model.evaluate({}, {}, s.inputs)
    return Result("rules.trace@own", "rule_trace", [], detail={"outputs": dict(out)})


def reference_trace(s: ReferenceSubject) -> Result:
    """For each reference-state variable: the value, the kb range, the status and the
    shift each coupled input puts on the variable's target."""
    m = s.model
    kb_inputs = dict(s.inputs)
    variables: dict[str, Any] = {}
    drivers = []
    for name in m.definition.variables:
        current = s.state.get(name)
        normal = m.normal(name)
        shifts = {}
        for cp in m.definition.couplings:
            if cp.target != name or kb_inputs.get(cp.input) is None:
                continue
            only = {cp.input: kb_inputs[cp.input]}
            shifts[cp.input] = (m.target(name, only, float(current or 0.0) if current is not None
                                         else 0.0) - (normal or 0.0))
        for src, shift in shifts.items():
            drivers.append(driver(f"{name} <- {src}", kb_inputs[src], float(shift)))
        variables[name] = {"value": current, "normal": normal,
                           "status": m.status(name, None if current is None else float(current)),
                           "range": m.definition.variables[name].ref, "shifts": shifts}
    return Result("reference.trace@own", "rule_trace", drivers,
                  output=None, detail={"variables": variables})


# ---------------------------------------------------------------------------
# Ontology justification (HermiT)
# ---------------------------------------------------------------------------

AXIOMS = ("observedIn", "ownedBy", "rule")


def _attributed(organ_instance: str, kind: DTKind, include: set[str]) -> bool:
    """Does HermiT conclude `attributedTo(obs, system)` from the included axioms?"""
    world = owl.World()
    onto = world.get_ontology(ontology.BASE.rstrip("#"))
    with onto:
        class System(owl.Thing):
            pass

        class Organ(owl.Thing):
            pass

        class Observation(owl.Thing):
            pass

        class ownedBy(Organ >> System, owl.FunctionalProperty):  # type: ignore[misc]
            pass

        class observedIn(Observation >> Organ, owl.FunctionalProperty):  # type: ignore[misc]
            pass

        class attributedTo(Observation >> System):  # type: ignore[misc]
            pass

        system_cls = owl.types.new_class(ontology._class_name(kind.value), (System,))
        organ = Organ("organ")
        owner = system_cls("owner")
        obs = Observation("obs")
        if "ownedBy" in include:
            organ.ownedBy = owner
        if "observedIn" in include:
            obs.observedIn = organ
        if "rule" in include:
            owl.Imp().set_as_rule(ontology.RULE)
    owl.reasoning.JAVA_MEMORY = HERMIT_JAVA_MB
    owl.sync_reasoner_hermit(world, infer_property_values=True, debug=0)
    return owner in list(obs.attributedTo)


def hermit_justification(organ_instance: str) -> Result:
    """Why an observation made in `organ_instance` is attributed to the organ's twin: the
    smallest set of axioms from which HermiT concludes it. Each axiom is removed in turn
    and the conclusion must disappear."""
    owner = load_registry().owner_of(organ_instance)
    if owner is None:
        raise KeyError(f"{organ_instance} has no owning twin")
    full = set(AXIOMS)
    if not _attributed(organ_instance, owner, full):
        raise RuntimeError("HermiT does not entail the attribution")
    needed = [a for a in AXIOMS if not _attributed(organ_instance, owner, full - {a})]
    if len(needed) < len(AXIOMS) and not _attributed(organ_instance, owner, set(needed)):
        raise RuntimeError("the axioms found are not sufficient")
    text = {"observedIn": f"the observation was made in {organ_instance}",
            "ownedBy": f"{organ_instance} is owned by the {owner.value} twin",
            "rule": "an observation made in an organ is attributed to the organ's owner"}
    return Result("hermit.justification@owlready2", "ontology_justification",
                  [driver(text[a], a, 1.0) for a in needed], output=1.0,
                  detail={"conclusion": f"observation attributedTo {owner.value}",
                          "axioms": [text[a] for a in needed]})


# ---------------------------------------------------------------------------
# Language-model answers
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z][a-z'-]+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")
_STOP = frozenset([
    "a", "an", "and", "are", "as", "at", "be", "but", "by", "for", "from", "has", "have", "if",
    "in", "is", "it", "its", "of", "on", "or", "that", "the", "their", "there", "these",
    "this", "to", "was", "were", "will", "with", "you", "your",
])


def sentences(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p.strip()]


def _content(text: str) -> set[str]:
    return {w for w in _WORD.findall(text.lower()) if w not in _STOP}


def numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text))


def citation_trace(s: TextSubject, min_overlap: float = 0.5) -> Result:
    """Each sentence of the answer matched to the source passage that supports it. A
    sentence is supported when its content words overlap a source by `min_overlap` and
    every number in it appears in that source."""
    rows = []
    cited: dict[str, int] = {}
    for sentence in sentences(s.answer):
        words, figures = _content(sentence), numbers(sentence)
        best, score = None, 0.0
        for sid, passage in s.sources.items():
            overlap = len(words & _content(passage)) / len(words) if words else 0.0
            if overlap > score and figures <= numbers(passage):
                best, score = sid, overlap
        supported = best is not None and score >= min_overlap
        rows.append({"sentence": sentence, "source": best if supported else None,
                     "overlap": round(score, 3), "supported": supported})
        if supported and best is not None:
            cited[best] = cited.get(best, 0) + 1
    share = sum(1 for r in rows if r["supported"]) / len(rows) if rows else 0.0
    return Result("citation.trace@own", "citation",
                  [driver(sid, n, float(n)) for sid, n in sorted(cited.items())],
                  output=share, detail={"sentences": rows, "supported_share": share})


def _similarity(a: str, b: str) -> float:
    wa, wb = _content(a), _content(b)
    if not wa and not wb:
        return 1.0
    jac = len(wa & wb) / len(wa | wb) if wa | wb else 1.0
    na, nb = numbers(a), numbers(b)
    figures = 1.0 if na == nb else len(na & nb) / len(na | nb) if na | nb else 1.0
    return 0.5 * jac + 0.5 * figures


def self_consistency(s: TextSubject, samples: int = 4) -> Result:
    """Mean pairwise similarity of the answer and `samples` more answers to the same prompt
    (word overlap plus agreement of the numbers). A low score marks an unstable answer."""
    if s.sample is None:
        raise ValueError("self-consistency needs a way to draw more answers")
    answers = [s.answer, *[s.sample() for _ in range(samples)]]
    pairs = [_similarity(a, b) for a, b in combinations(answers, 2)]
    score = sum(pairs) / len(pairs)
    return Result("self_consistency@own", "citation", [], output=score,
                  uncertainty={"self_consistency": score, "samples": len(answers)},
                  detail={"answers": answers})
