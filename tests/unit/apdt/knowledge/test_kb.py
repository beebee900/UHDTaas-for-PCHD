import pytest

from apdt.knowledge.kbcheck import problems
from apdt.knowledge.numcheck import check_kb, derived_match, text_numbers
from apdt.knowledge.sections import TREES
from apdt.knowledge.sources import load_lock, load_sources
from atra.config import ROOT
from atra.kb import KnowledgeBase

needs_trees = pytest.mark.skipif(not any(TREES.glob("*.json")) if TREES.exists() else True,
                                 reason="section trees are built by `make kb-sources`")


def test_kb_structure():
    assert problems() == []


def test_every_source_is_well_formed_and_located_sources_are_locked():
    sources = load_sources()
    lock = load_lock()
    for src in sources.values():
        if src.status == "located" and src.format in ("pdf", "jats", "html", "json") \
                and src.data_via is None:
            assert src.id in lock, f"{src.id} has no lock entry"


def test_assumptions_are_justified():
    kb = KnowledgeBase(ROOT / "kb")
    for eid in kb.ids():
        prov = kb.entry(eid).provenance
        assert not prov.assumption or prov.justification, eid


@needs_trees
def test_number_check_has_no_failures():
    report = check_kb()
    assert [line for line in report.summary_lines() if line.startswith("FAIL")] == []


def test_text_numbers_reads_source_notation():
    found = text_numbers("≥ 26.5 μmol/l, 10 000/µL, 1·5 times, 1,000 mg, X0.3mg/dl")
    assert {26.5, 10000.0, 1.5, 1000.0, 0.3} <= found


def test_derived_paths_match_literally():
    assert derived_match("bands[0].*_total", "bands[0].min_total")
    assert not derived_match("bands[0].*_total", "bands0.min_total")
    assert derived_match("groups[*].age_from_months", "groups[3].age_from_months")


def test_kb_lookup_selects_by_key_and_index():
    kb = KnowledgeBase(ROOT / "kb")
    assert kb.lookup("news2.bands", "bands[band=high].min_total") == 7
    assert kb.lookup("news2.bands", "bands[0].band") == "low"
    with pytest.raises(KeyError):
        kb.lookup("news2.bands", "bands[band=none].min_total")


def test_code_to_twin_is_current_and_covers_every_condition(tmp_path):
    from apdt.knowledge.code_map import read, write

    write(tmp_path / "map.csv")
    assert (tmp_path / "map.csv").read_text() == (ROOT / "kb" / "code_to_twin.csv").read_text(), \
        "run `python -m apdt.knowledge.sourcing code-map`"
    table = read()
    kb = KnowledgeBase(ROOT / "kb")
    for eid in kb.ids():
        if eid.startswith("cond."):
            content = kb.entry(eid).content()
            assert table[("snomed", str(content["snomed"]))] in (content["twin"],), eid


def test_tenant_data_is_reproducible(tmp_path):
    import shutil

    from apdt.knowledge.tenant_data import TENANTS, write

    shutil.copytree(ROOT / "kb", tmp_path / "kb")
    write(tmp_path / "kb")
    for tenant in TENANTS:
        for rel in (f"stock/{tenant}.csv", f"prices/{tenant}.csv", f"rota/{tenant}.yaml"):
            assert (tmp_path / "kb" / rel).read_text() == (ROOT / "kb" / rel).read_text(), rel


def test_questionnaires_are_current_and_valid_fhir(tmp_path):
    import json
    import shutil

    from fhir.resources.R4B.questionnaire import Questionnaire

    from apdt.knowledge.questionnaires import write

    shutil.copytree(ROOT / "kb", tmp_path / "kb")
    shutil.rmtree(tmp_path / "kb" / "questionnaires")
    for path in write(tmp_path / "kb"):
        committed = ROOT / "kb" / "questionnaires" / path.name
        assert path.read_text() == committed.read_text(), \
            "run `python -m apdt.knowledge.sourcing questionnaires`"
        Questionnaire.model_validate(json.loads(path.read_text()))


def test_pathways_are_current_valid_and_replayable(tmp_path):
    import json
    import shutil

    import pandas as pd
    import pm4py
    from fhir.resources.R4B.plandefinition import PlanDefinition

    from apdt.knowledge.pathways import TASK_NAMES, write

    shutil.copytree(ROOT / "kb", tmp_path / "kb")
    for path in write(tmp_path / "kb"):
        committed = ROOT / "kb" / path.parent.name / path.name
        assert path.read_text() == committed.read_text(), \
            "run `python -m apdt.knowledge.sourcing pathways`"
        if path.suffix == ".json":
            PlanDefinition.model_validate(json.loads(path.read_text()))
    bpmn = pm4py.read_bpmn(str(ROOT / "kb/pathways/acute_febrile.bpmn"))
    net, im, fm = pm4py.convert_to_petri_net(bpmn)

    def fitness(tasks):
        df = pd.DataFrame({"case": "1", "act": [TASK_NAMES[t] for t in tasks],
                           "ts": pd.date_range("2026-01-01", periods=len(tasks), freq="h")})
        log = pm4py.format_dataframe(df, case_id="case", activity_key="act", timestamp_key="ts")
        return pm4py.fitness_token_based_replay(log, net, im, fm)["log_fitness"]

    assert fitness(["register", "triage", "history", "examine", "test", "diagnose", "refer",
                    "follow_up", "discharge"]) == 1.0
    assert fitness(["register", "history", "treat", "discharge"]) < 1.0


def test_instrument_scoring():
    from apdt.knowledge.questionnaires import score

    kb = KnowledgeBase(ROOT / "kb")
    gad7 = kb.entry("instrument.gad7").content()
    assert score(gad7, {str(i): "2" for i in range(1, 8)}) == {"total": 14.0}

    promis = kb.entry("instrument.promis10").content()
    best = {i["id"]: "5" for i in promis["items"]} | {"Global07r": "0"}
    assert score(promis, best) == {"global_physical": 67.7, "global_physical.se": 5.9,
                                   "global_mental": 67.6, "global_mental.se": 5.3}
    # Pain 5 of 10 recodes to 3: physical raw 3 + 3 + 3 + 3 = 12.
    mid = {i["id"]: "3" for i in promis["items"]} | {"Global07r": "5"}
    assert score(promis, mid)["global_physical"] == 39.8
    assert score(promis, mid)["global_mental"] == 43.5
