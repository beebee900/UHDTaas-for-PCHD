from pathlib import Path

import pytest

from ahdt.registry import iter_kb_refs, load_registry
from atra.config import ROOT
from atra.connector_contracts import expanded_pairs
from atra.connectors import DTKind
from atra.kb import KnowledgeBase
from atra.units import quantity

REGISTRY = load_registry()
KB = KnowledgeBase(ROOT / "kb")
UBERON = ROOT / "var" / "ontologies" / "uberon-basic.obo"


def test_registry_is_consistent():
    assert REGISTRY.problems() == []


def test_every_field_unit_is_valid_ucum():
    for twin in REGISTRY.twins.values():
        for f in twin.fields:
            quantity(1, f.ucum)


def test_every_kb_reference_resolves():
    for twin in REGISTRY.twins.values():
        for f in twin.fields:
            assert f.ref in KB, f.ref
        for goal in twin.standing_goals:
            for ref in iter_kb_refs(goal.check.params):
                assert ref in KB, ref


def test_connectors_listed_on_both_ends():
    for name, src, dst in expanded_pairs():
        if src.is_ahdt_member:
            assert name in REGISTRY.twins[src].connectors_out
        if dst.is_ahdt_member:
            assert name in REGISTRY.twins[dst].connectors_in


def test_each_physiological_twin_reports_to_whole_body():
    for kind in DTKind:
        if kind.is_physiological:
            assert "SystemToWholeBodyConnector" in REGISTRY.twins[kind].connectors_out


@pytest.mark.skipif(not UBERON.exists(), reason="UBERON release not downloaded")
def test_uberon_ids_exist():
    ids = {line[4:].strip() for line in UBERON.read_text().splitlines()
           if line.startswith("id: UBERON:")}
    used = {i for t in REGISTRY.twins.values() for i in t.owns_instances if i.startswith("UBERON:")}
    assert used - ids == set()


def test_kb_drafts_cite_a_source_or_justify_an_assumption():
    for entry_id in KB.drafts():
        prov = KB.entry(entry_id).provenance
        if prov.assumption:
            assert prov.justification, entry_id
        else:
            assert prov.source and (prov.section or prov.page), entry_id


def test_kb_rejects_duplicate_ids(tmp_path: Path):
    (tmp_path / "a.yaml").write_text("- {id: x, value: 1, provenance: {status: draft}}\n")
    (tmp_path / "b.yaml").write_text("- {id: x, value: 2, provenance: {status: draft}}\n")
    with pytest.raises(ValueError, match="defined twice"):
        KnowledgeBase(tmp_path)


def test_kb_resolves_references():
    assert KB.resolve_refs({"above": {"kb": "goal.cv.forecast_sbp"}}) == {"above": 140}
