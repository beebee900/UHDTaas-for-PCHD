import bz2
import json
import os
from dataclasses import replace
from datetime import UTC, datetime

import owlready2
import pytest
from rdflib import Graph

from ahdt.ingest import build_pipeline
from ahdt.ingest.harmonise import RawObservation
from ahdt.knowledge import communities, owl, queries
from ahdt.knowledge.answer import GraphQA, seed
from ahdt.knowledge.documents import Notes
from ahdt.knowledge.extraction import NoteExtractor
from ahdt.knowledge.hetionet import STORE_DIR as HETIONET_STORE
from ahdt.knowledge.hetionet import records
from ahdt.knowledge.ontology import STORE_DIR as ONTOLOGY_STORE
from ahdt.knowledge.ontology import Ontologies, read_obo
from ahdt.knowledge.phkg import PHKG, condition_id
from ahdt.knowledge.rdf import FhirRdf
from ahdt.knowledge.service import KnowledgeService
from ahdt.knowledge.sparql import SparqlStore
from ahdt.registry import load_registry
from atra.backends import Backends
from atra.backends.graph import NetworkXGraph
from atra.backends.memory import MemoryFhir
from atra.config import Settings
from atra.connectors import DTKind
from atra.consent import demo_registry
from atra.contracts import Code, KnowledgeArgs
from atra.personas import BY_KEY
from atra.provenance import AuditLog
from atra.service import Problem
from synth.personas import facts

GH = BY_KEY["gh"].hdt_id
DE = BY_KEY["de"].hdt_id
STATEMENTS = {name: value for name, value in vars(queries).items()
              if name.isupper() and isinstance(value, str)}


def params_for(stmt):
    return {"id": "x", "props": {"id": "x"}, "a": "x", "b": "y", "hdt_id": "hdt-000000000000",
            "field": "f", "kind": "k"} if "$" in stmt else {}


@pytest.mark.parametrize("name", sorted(STATEMENTS))
async def test_every_statement_runs_in_process(name):
    await NetworkXGraph().run(STATEMENTS[name], params_for(STATEMENTS[name]))


@pytest.mark.profile("p1")
@pytest.mark.parametrize("name", sorted(STATEMENTS))
async def test_every_statement_runs_on_neo4j(name):
    from atra.backends.graph import Neo4jGraph

    graph = Neo4jGraph(Settings().infra.neo4j, "neo4j",
                       os.environ.get("ATRA_NEO4J_PASSWORD", "atra-neo4j"))
    try:
        await graph.run(STATEMENTS[name], params_for(STATEMENTS[name]))
    finally:
        await graph.close()


@pytest.fixture
async def phkg():
    graph = PHKG(NetworkXGraph())
    for key in ("de", "gh"):
        await seed(graph, BY_KEY[key].hdt_id, facts()[key])
    return graph


def test_obo_reader_streams_terms(tmp_path):
    obo = tmp_path / "x.obo"
    obo.write_text("format-version: 1.2\n\n[Term]\nid: X:1\nname: root\n\n[Term]\nid: X:2\n"
                   "name: child\nis_a: X:1 ! root\nxref: http://a.b/Category\\:C\n\n[Term]\n"
                   "id: X:3\nname: gone\nis_obsolete: true\n\n[Typedef]\nid: part_of\n")
    assert list(read_obo(obo)) == [("X:1", "root", []), ("X:2", "child", ["X:1"])]


@pytest.mark.skipif(not ONTOLOGY_STORE.exists(), reason="ontology store not built")
def test_ontology_store_answers_labels_and_ancestry():
    onto = Ontologies()
    assert onto.label("UBERON:0000948") == "heart"
    assert onto.is_a("UBERON:0000948", "UBERON:0000062")
    used = {i for t in load_registry().twins.values() for i in t.owns_instances
            if i.startswith("UBERON:")}
    assert {i for i in used if not onto.exists(i)} == set()


def test_hermit_attributes_every_organ_to_its_owner(tmp_path):
    path = owl.write(tmp_path / "ahdt.owl")
    inferred = owl.check(path)
    registry = load_registry()
    for kind, twin in registry.twins.items():
        for instance in twin.owns_instances:
            assert inferred[instance] == owl._class_name(kind.value)


def test_hermit_rejects_an_organ_owned_by_two_twins(tmp_path):
    registry = load_registry()
    cv, rs = registry.twins[DTKind.CARDIOVASCULAR], registry.twins[DTKind.RESPIRATORY]
    twins = dict(registry.twins)
    twins[DTKind.RESPIRATORY] = rs.model_copy(
        update={"owns_instances": [*rs.owns_instances, cv.owns_instances[0]]})
    _, onto = owl.build(replace(registry, twins=twins))
    path = tmp_path / "bad.owl"
    onto.save(file=str(path), format="rdfxml")
    with pytest.raises(owlready2.OwlReadyInconsistentOntologyError):
        owl.check(path)


def test_committed_ontology_matches_the_registry():
    text = owl.OWL_PATH.read_text()
    for twin in load_registry().twins.values():
        for instance in twin.owns_instances:
            assert instance.replace(":", "_") in text


async def test_ingested_observations_reach_the_phkg(tmp_path):
    backends = Backends(Settings(var_dir=tmp_path), "ahdt", ephemeral=True)
    pipeline = await build_pipeline(backends, demo_registry(), AuditLog("ahdt"))
    graph = PHKG(backends.graph)
    graph.subscribe(backends.events)
    hdt = BY_KEY["ao"].hdt_id
    await pipeline.process([RawObservation(
        record_id="t1", hdt_id=hdt, code=Code(system="http://loinc.org", code="8310-5"),
        value=38.6, unit="Cel", effective_time=datetime(2026, 10, 1, 8, tzinfo=UTC))])
    await backends.events.drain()
    obs = (await graph.read("person.observation", hdt, {"field": "temperature"}))[0]["b"]
    assert obs["value"] == 38.6 and obs["record_id"] == "t1"
    owner = await graph.read("fact.owner", hdt, {"id": obs["id"]})
    assert owner[0]["b"]["kind"] == "immune_lymphatic"
    await backends.close()


async def test_interactions_match_combination_components(phkg):
    meds = await phkg.read("person.medications", GH)
    found = phkg.interaction_entries([(m["b"]["atc"], m["b"]["name"]) for m in meds])
    assert ("J05AR27", "J04AM06", "ix.dolutegravir.rifampicin") in found
    linked = await phkg.read("medication.interactions", GH, {"id": f"med:{GH}:J05AR27"})
    assert linked[0]["b"]["atc"] == "J04AM06"


async def test_graph_query_cites_nodes_and_refuses_without_answer(phkg):
    qa = GraphQA(phkg)
    ans = await qa.ask(DE, "Which twin owns his hypertension?", "graphrag")
    assert "Cardiovascular DT" in ans.answer
    assert {c["node_id"] for c in ans.citations} == {
        condition_id(DE, "snomed", "59621000"), "system:cardiovascular"}
    from ahdt.knowledge.answer import NoAnswer

    with pytest.raises(NoAnswer):
        await qa.ask(DE, "Explain the NEWS2 score bands.", "graphrag")


async def test_communities_cluster_the_person_graph(phkg):
    found = await communities.build(phkg, DE)
    assert found and all(c["summary"] and c["method"] == "extractive" for c in found)
    members = {m for c in found for m in c["members"]}
    assert condition_id(DE, "snomed", "59621000") in members
    stored = await phkg.read("person.communities", DE)
    assert len(stored) == len(found)


def test_note_extraction_handles_negation_and_uncertainty():
    ex = NoteExtractor().extract(
        "History of Present Illness: cough and weight loss for three weeks. No fever.\n"
        "Assessment: possible pulmonary tuberculosis.")
    findings = {m.text.lower(): m for m in ex.findings}
    assert findings["fever"].negated and not findings["cough"].negated
    tb = ex.conditions[0]
    assert tb.ref == "cond.tb_pulmonary" and tb.uncertain


async def test_notes_are_sectioned_searched_and_linked(phkg):
    notes = Notes(MemoryFhir(), phkg)
    await notes.add(GH, "note", "History of Present Illness: cough for three weeks.\n"
                    "Assessment: possible pulmonary tuberculosis.\nPlan: sputum Xpert test.",
                    date=datetime(2026, 10, 2, tzinfo=UTC))
    hits = await notes.search(GH, "sputum test")
    assert hits[0]["section_path"][0] == "note" and "plan" in hits[0]["section_path"][1]
    tb = await phkg.read("person.conditions", GH)
    assert any(r["b"]["kb_id"] == "cond.tb_pulmonary" for r in tb)


async def test_rdf_export_and_sparql(phkg):
    rdf = FhirRdf()
    rdf.resource({"resourceType": "Observation", "id": "o1", "status": "final",
                  "code": {"coding": [{"system": "http://loinc.org", "code": "8480-6"}]},
                  "subject": {"reference": f"Patient/{DE}"},
                  "effectiveDateTime": "2026-10-01T08:00:00+00:00",
                  "valueQuantity": {"value": 162, "unit": "mm[Hg]"}})
    rdf.phkg(*await phkg.subgraph(DE))
    ttl = rdf.turtle()
    parsed = Graph().parse(data=ttl, format="turtle")
    assert len(parsed) > 20 and "fhir:treeRoot" in ttl and "loinc.org/rdf#8480-6" in ttl
    store = SparqlStore()
    store.load_person(DE, ttl)
    rows = store.read("observations", DE)
    assert rows == [{"resource": "https://atra.health/fhir/Observation/o1", "code": "8480-6",
                     "value": "162"}]
    names = {r["name"] for r in store.read("conditions", DE)}
    assert "Hypertension" in names


async def test_knowledge_tool_is_allow_listed_and_person_scoped(tmp_path, phkg):
    service = KnowledgeService(Backends(Settings(var_dir=tmp_path), "ahdt", ephemeral=True))
    service.phkg = phkg
    rows = (await service.knowledge(KnowledgeArgs(hdt_id=DE, query_id="person.conditions",
                                                  params={}), None))["rows"]
    assert len(rows) == 3
    with pytest.raises(Problem) as err:
        await service.knowledge(KnowledgeArgs(hdt_id=DE, query_id="fact.owner",
                                              params={"id": f"cond:{GH}:snomed:86406008"}), None)
    assert err.value.status == 403
    with pytest.raises(Problem):
        await service.knowledge(KnowledgeArgs(hdt_id=DE, query_id="MATCH (n) RETURN n",
                                              params={}), None)


def test_hetionet_reader_streams_the_release_layout(tmp_path):
    doc = {"metanode_kinds": ["Disease"], "nodes": [
        {"kind": "Disease", "identifier": "DOID:1", "name": "a", "data": {}},
        {"kind": "Gene", "identifier": 7, "name": "G", "data": {}}],
        "edges": [{"source_id": ["Disease", "DOID:1"], "target_id": ["Gene", 7],
                   "kind": "associates", "direction": "both", "data": {}}]}
    path = tmp_path / "h.json.bz2"
    path.write_bytes(bz2.compress(json.dumps(doc, indent=2).encode()))
    got = list(records(path))
    assert [s for s, _ in got] == ["nodes", "nodes", "edges"]
    assert got[2][1]["kind"] == "associates"


@pytest.mark.skipif(not HETIONET_STORE.exists(), reason="Hetionet store not built")
def test_hetionet_store_links_kb_conditions():
    from ahdt.knowledge.hetionet import Hetionet

    het = Hetionet()
    disease = het.disease("cond.hypertension")
    assert disease and "Amlodipine" in het.neighbours(disease, "treats", "Compound")


@pytest.mark.slow
def test_scripted_graph_questions_all_pass():
    import asyncio

    from evaluation.graph_query.run import run

    summary = asyncio.run(run())
    assert summary["passed"] == summary["total"] == 20, [
        r for r in summary["results"] if not r["pass"]]


@pytest.mark.profile("p1")
def test_neo4j_vector_retrieval_finds_the_section():
    from ahdt.knowledge.graphrag_neo4j import GuidelineVectors

    vectors = GuidelineVectors(Settings().infra.neo4j, "neo4j",
                               os.environ.get("ATRA_NEO4J_PASSWORD", "atra-neo4j"))
    try:
        vectors.load([("doc-test", "doc-test#1", "Artesunate", "Give artesunate for severe "
                       "malaria."), ("doc-test", "doc-test#2", "NEWS2", "Score the vital signs.")])
        hits = vectors.search("treatment of severe malaria", top_k=1)
        assert hits[0]["section_id"] == "doc-test#1"
    finally:
        vectors.close()
