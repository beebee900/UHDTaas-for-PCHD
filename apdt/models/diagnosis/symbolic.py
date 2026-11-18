"""Neuro-symbolic layer over the patient clinical graph (design 05, 5.5.1).

The patient's facts form an RDF graph. SHACL shapes (pySHACL) express the hard exclusions: a
candidate whose gate fails (`hard_gates` in params.yaml) violates its shape and leaves the
list. A SPARQL query finds the red-flag findings of the kb conditions (`red_flags` in
kb/conditions.yaml): a condition with a red flag present and some supporting evidence is forced
onto the list as "must rule out". The layer decides list membership only. It never sets or
changes a probability. A second set of shapes validates that every treatment option carries
its sources and its drug identifiers.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from apdt.models.context import Observations, Patient, kb, param
from apdt.models.diagnosis.bn import Candidate, Differential
from apdt.models.treatment.options import Option

NS = "https://atra.health/ns#"


@dataclass(frozen=True)
class Excluded:
    condition: str
    reason: str


@dataclass(frozen=True)
class MustRuleOut:
    condition: str
    name: str
    red_flags: tuple[str, ...]


@dataclass
class Listing:
    listed: list[Candidate]
    excluded: list[Excluded] = field(default_factory=list)
    must_rule_out: list[MustRuleOut] = field(default_factory=list)


def _local(condition: str) -> str:
    return condition.replace(".", "_")


def patient_graph(patient: Patient, obs: Observations, candidates: Sequence[str]) -> Any:
    from rdflib import RDF, Graph, Literal, Namespace

    ns = Namespace(NS)
    g = Graph()
    g.bind("atra", ns)
    me = ns["patient"]
    g.add((me, RDF.type, ns.Patient))
    g.add((me, ns.sex, Literal(patient.sex)))
    g.add((me, ns.pregnancy, Literal(patient.pregnancy)))
    g.add((me, ns.ageYears, Literal(patient.age_years)))
    if patient.hb_genotype:
        g.add((me, ns.hbGenotype, Literal(patient.hb_genotype)))
    for finding, present in obs.findings.items():
        if present:
            g.add((me, ns.hasFinding, ns[_local(finding)]))
    for cond in candidates:
        node = ns[f"cand_{_local(cond)}"]
        g.add((node, RDF.type, ns.Candidate))
        g.add((node, RDF.type, ns[f"Candidate_{_local(cond)}"]))
        g.add((node, ns.ofPatient, me))
        g.add((node, ns.condition, Literal(cond)))
    return g


def exclusion_shapes() -> Any:
    """One SHACL node shape per gated condition."""
    from rdflib import RDF, SH, BNode, Graph, Literal, Namespace
    from rdflib.collection import Collection

    ns = Namespace(NS)
    g = Graph()
    props = {"hb_genotype": ns.hbGenotype, "sex": ns.sex, "pregnancy": ns.pregnancy}
    for cond, gate in param("hard_gates").items():
        shape = ns[f"shape_{_local(cond)}"]
        g.add((shape, RDF.type, SH.NodeShape))
        g.add((shape, SH.targetClass, ns[f"Candidate_{_local(cond)}"]))
        for key, allowed in gate.items():
            prop, path, values = BNode(), BNode(), BNode()
            Collection(g, path, [ns.ofPatient, props[key]])
            Collection(g, values, [Literal(v) for v in allowed])
            g.add((shape, SH.property, prop))
            g.add((prop, SH.path, path))
            g.add((prop, SH["in"], values))
            g.add((prop, SH.minCount, Literal(1)))
            g.add((prop, SH.message, Literal(f"{key} must be one of {', '.join(allowed)}")))
    return g


def _violations(data: Any, shapes: Any) -> list[tuple[str, str]]:
    """(focus node, message) of every SHACL violation."""
    from pyshacl import validate
    from rdflib import RDF, SH

    conforms, report, _ = validate(data, shacl_graph=shapes, inference="none")
    if conforms:
        return []
    return sorted({(str(report.value(r, SH.focusNode)), str(report.value(r, SH.resultMessage)))
                   for r in report.subjects(RDF.type, SH.ValidationResult)})


def red_flag_query(g: Any) -> dict[str, list[str]]:
    """Present red-flag findings per condition, by SPARQL over the patient graph."""
    out: dict[str, list[str]] = {}
    for entry_id in kb().ids():
        if not entry_id.startswith("cond."):
            continue
        flags = kb().entry(entry_id).content().get("red_flags", [])
        if not flags:
            continue
        values = " ".join(f"atra:{_local(f)}" for f in flags)
        rows = g.query(f"PREFIX atra: <{NS}> SELECT ?f WHERE {{ atra:patient atra:hasFinding ?f . "
                       f"VALUES ?f {{ {values} }} }}")
        present = sorted(str(r["f"]).removeprefix(NS).replace("find_", "find.") for r in rows)
        if present:
            out[entry_id] = present
    return out


def apply(diff: Differential, patient: Patient, obs: Observations) -> Listing:
    """List the candidates: the differential's, minus exclusions, plus forced conditions."""
    cut = float(param("listing_threshold"))
    names = [c.condition for c in diff.candidates]
    graph = patient_graph(patient, obs, names)
    found = _violations(graph, exclusion_shapes())
    violated = {focus.removeprefix(NS + "cand_") for focus, _ in found}
    messages = dict(found)
    listing = Listing([])
    for cand in diff.candidates:
        key = _local(cand.condition)
        if key in violated:
            listing.excluded.append(Excluded(cand.condition,
                                             messages.get(NS + f"cand_{key}", "gate failed")))
        elif cand.probability >= cut:
            listing.listed.append(cand)
    flags = red_flag_query(graph)
    for cand in diff.candidates:
        if cand.condition in flags and cand not in listing.listed \
                and _local(cand.condition) not in violated:
            listing.listed.append(cand)
            listing.must_rule_out.append(MustRuleOut(cand.condition, cand.name,
                                                     tuple(flags[cand.condition])))
    return listing


def option_shapes() -> Any:
    from rdflib import RDF, SH, BNode, Graph, Literal, Namespace

    ns = Namespace(NS)
    g = Graph()
    option_shape, dose_shape = ns.OptionShape, ns.DoseShape
    g.add((option_shape, RDF.type, SH.NodeShape))
    g.add((option_shape, SH.targetClass, ns.Option))
    cite = BNode()
    g.add((option_shape, SH.property, cite))
    g.add((cite, SH.path, ns.citation))
    g.add((cite, SH.minCount, Literal(1)))
    g.add((cite, SH.message, Literal("an option needs a cited source")))
    reg = BNode()
    g.add((option_shape, SH.property, reg))
    g.add((reg, SH.path, ns.regimen))
    g.add((reg, SH.node, dose_shape))
    g.add((dose_shape, RDF.type, SH.NodeShape))
    drug = BNode()
    g.add((dose_shape, SH.property, drug))
    g.add((drug, SH.path, ns.drug))
    g.add((drug, SH.minCount, Literal(1)))
    g.add((drug, SH.message, Literal("a dose needs a drug name")))
    return g


def validate_options(options: Sequence[Option]) -> list[tuple[str, str]]:
    """(option id, message) for every option that breaks its shape."""
    from rdflib import RDF, Graph, Literal, Namespace

    ns = Namespace(NS)
    g = Graph()
    for o in options:
        node = ns[_local(o.option_id)]
        g.add((node, RDF.type, ns.Option))
        for c in o.citations:
            g.add((node, ns.citation, Literal(f"{c.source}:{c.section}")))
        for i, d in enumerate(o.doses):
            dose = ns[f"{_local(o.option_id)}_dose{i}"]
            g.add((node, ns.regimen, dose))
            if d.drug:
                g.add((dose, ns.drug, Literal(d.drug)))
    return [(f.removeprefix(NS), m) for f, m in _violations(g, option_shapes())]
