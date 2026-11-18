"""The SHACL exclusion layer, the red-flag query and the option shapes."""

from __future__ import annotations

from apdt.models.context import Observations, Patient
from apdt.models.diagnosis import symbolic
from apdt.models.diagnosis.bn import DifferentialModel
from apdt.models.reasoning import ClinicalReasoner
from evaluation.models.apdt.scenarios import BY_SCENARIO

MODEL = DifferentialModel()


def test_gate_failure_removes_a_candidate_through_shacl() -> None:
    obs = Observations(findings={"find.bone_pain": True})
    male = Patient(30.0, "male", 70.0, hb_genotype="HbAA")
    diff = MODEL.differential(male, obs)
    names = [c.condition for c in diff.candidates]
    assert "cond.scd_crisis" not in names or diff.marginals["cond.scd_crisis"] == 0.0
    graph = symbolic.patient_graph(male, obs, ["cond.scd_crisis"])
    found = symbolic._violations(graph, symbolic.exclusion_shapes())
    assert found and found[0][0].endswith("cand_cond_scd_crisis")
    assert "hb_genotype" in found[0][1]
    hbss = Patient(30.0, "male", 70.0, hb_genotype="HbSS")
    ok = symbolic.patient_graph(hbss, obs, ["cond.scd_crisis"])
    assert symbolic._violations(ok, symbolic.exclusion_shapes()) == []


def test_symbolic_layer_never_changes_probabilities() -> None:
    s = BY_SCENARIO["ef"]
    patient, obs = ClinicalReasoner(MODEL).prepare(s.patient, s.observations)
    diff = MODEL.differential(patient, obs)
    listing = symbolic.apply(diff, patient, obs)
    by_name = {c.condition: c.probability for c in diff.candidates}
    assert listing.listed and all(c.probability == by_name[c.condition] for c in listing.listed)
    assert listing.listed[0].condition == "cond.scd_crisis"


def test_red_flags_force_a_condition_onto_the_list() -> None:
    s = BY_SCENARIO["bm"]
    patient, obs = ClinicalReasoner(MODEL).prepare(s.patient, s.observations)
    obs.tests.clear()
    diff = MODEL.differential(patient, obs)
    listing = symbolic.apply(diff, patient, obs)
    forced = {m.condition: m for m in listing.must_rule_out}
    graph = symbolic.patient_graph(patient, obs, [])
    flags = symbolic.red_flag_query(graph)
    assert "cond.malaria_falciparum" in flags
    assert "find.impaired_consciousness" in flags["cond.malaria_falciparum"]
    assert "cond.malaria_falciparum" in {c.condition for c in listing.listed} or forced


def test_options_need_sources_and_drugs() -> None:
    s = BY_SCENARIO["ao"]
    a = ClinicalReasoner(MODEL).assess(s.patient, s.observations, with_tests=False)
    options = a.options["cond.malaria_falciparum"].eligible
    assert symbolic.validate_options(options) == []
    options[0].citations.clear()
    broken = symbolic.validate_options(options)
    assert broken and "cited source" in broken[0][1]
