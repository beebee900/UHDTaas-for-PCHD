"""Network inference, test selection, interpretation and the comparator."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np
import pytest

from apdt.models.context import Observations, Patient
from apdt.models.diagnosis import bn
from apdt.models.diagnosis.bn import VARIANTS, DifferentialModel, Enumerator, Evidence
from apdt.models.diagnosis.comparator import MODEL_ID, Comparator
from apdt.models.diagnosis.interpret import delta_check, derive_findings, interpret
from apdt.models.diagnosis.tests_select import rank_tests
from evaluation.models.apdt.cohort import generate_cohort
from evaluation.models.apdt.scenarios import BY_SCENARIO
from evaluation.models.apdt.train import fit_bma_weights, split_cases, train

ADULT = Patient(40.0, "female", 60.0)


@lru_cache(maxsize=1)
def model() -> DifferentialModel:
    return DifferentialModel()


def febrile() -> Observations:
    return Observations(findings={"find.fever": True, "find.fever_history": True})


def test_network_uses_the_kb_strengths() -> None:
    net = bn.build_network()
    fever = net.findings["find.fever"]
    assert fever.links["cond.malaria_falciparum"] == pytest.approx(0.95)
    assert fever.links["cond.pyelonephritis"] == pytest.approx(0.6)
    assert fever.leak == pytest.approx(0.02)
    rdt = net.tests["test.malaria_rdt_hrp2"]
    assert rdt.leak == pytest.approx(0.048)


def test_a_positive_rdt_raises_malaria() -> None:
    before = model().differential(ADULT, febrile()).marginals["cond.malaria_falciparum"]
    obs = febrile()
    obs.tests["test.malaria_rdt_hrp2"] = True
    after = model().differential(ADULT, obs).marginals["cond.malaria_falciparum"]
    assert after > before and after > 0.9
    obs.tests["test.malaria_rdt_hrp2"] = False
    negative = model().differential(ADULT, obs).marginals["cond.malaria_falciparum"]
    assert negative < before


@pytest.mark.parametrize("variant", VARIANTS)
def test_pgmpy_agrees_with_enumeration(variant: str) -> None:
    obs = Observations(findings={"find.fever": True, "find.cough": True, "find.headache": False},
                       tests={"test.malaria_rdt_hrp2": False})
    pri = {c: v[0] for c, v in model().priors(ADULT).items()}
    evidence = Evidence.of(obs)
    enum = Enumerator(model().net, pri, evidence)
    exact = enum.marginals(enum.state_posterior(variant))
    other = bn.pgmpy_posterior(model().net, pri, evidence, variant)
    assert other.keys() == exact.keys()
    for c in exact:
        assert other[c] == pytest.approx(exact[c], abs=1e-9)


def test_pgmpy_engine_in_the_model() -> None:
    a = model().differential(ADULT, febrile(), engine="pgmpy")
    b = model().differential(ADULT, febrile())
    assert a.marginals.keys() == b.marginals.keys()
    for c, p in b.marginals.items():
        assert a.marginals[c] == pytest.approx(p, abs=1e-9)


def test_variants_differ_in_comorbidity() -> None:
    obs = Observations(findings={"find.fever": True, "find.raised_bp": True})
    d = model().differential(ADULT, obs)
    htn = next(c for c in d.candidates if c.condition == "cond.hypertension")
    assert htn.variants["independent"] > 0.9
    assert htn.variants["exclusive"] < htn.variants["independent"]


def test_gates_remove_impossible_conditions() -> None:
    obs = Observations(findings={"find.bone_pain": True})
    male = Patient(30.0, "male", 70.0, hb_genotype="HbAA")
    assert model().differential(male, obs).candidates == ()
    hbss = Patient(30.0, "male", 70.0, hb_genotype="HbSS")
    assert model().differential(hbss, obs).top().condition == "cond.scd_crisis"  # type: ignore[union-attr]


def test_priors_cite_their_source() -> None:
    candidates = model().differential(ADULT, febrile()).candidates
    sources = {c.condition: c.prior_source for c in candidates}
    assert sources["cond.malaria_falciparum"] == "kb:prior.malaria_falciparum"
    assert sources["cond.enteric_fever"] == "assumption:default_prior"


def test_dropping_conditions_is_reported() -> None:
    net = bn.build_network()
    pri = {c: 0.01 for c in net.conditions}
    obs = Observations(findings={f: False for f in list(net.findings)[:40]})
    obs.findings["find.fever"] = True
    enum = Enumerator(net, pri, Evidence.of(obs), limit=8)
    assert len(enum.relevant) == 8 and enum.dropped
    assert "cond.malaria_falciparum" in enum.relevant


def test_test_ranking_prefers_informative_cheap_tests() -> None:
    scores, changes = rank_tests(model(), ADULT, febrile())
    assert scores and scores[0].voi > 0
    ids = [s.test_id for s in scores]
    assert "test.malaria_rdt_hrp2" in ids
    rdt = next(s for s in scores if s.test_id == "test.malaria_rdt_hrp2")
    assert rdt.top_if_positive == "cond.malaria_falciparum"
    assert all(s.score >= 0 for s in scores)
    assert scores == sorted(scores, key=lambda s: -s.score)
    assert all(c.new_top != "cond.malaria_falciparum" for c in changes
               if c.test_id == "test.malaria_rdt_hrp2")


def test_known_results_are_not_ranked_again() -> None:
    obs = febrile()
    obs.tests["test.malaria_rdt_hrp2"] = True
    scores, _ = rank_tests(model(), ADULT, obs)
    assert "test.malaria_rdt_hrp2" not in {s.test_id for s in scores}


def test_interpretation_uses_patient_specific_limits() -> None:
    low = interpret("hb", 11.5, Patient(30.0, "female", 60.0))
    assert low is not None and low.flag == "low"
    pregnant = interpret("hb", 11.2, Patient(30.0, "female", 60.0, pregnancy="t2"))
    assert pregnant is not None and pregnant.flag == "normal"
    critical = interpret("glucose", 2.1, ADULT)
    assert critical is not None and critical.level == "critical" and critical.critical_hits


def test_delta_checks() -> None:
    assert delta_check("temperature", 41.0, 36.5, 1.0).flagged
    assert not delta_check("temperature", 37.0, 36.5, 6.0).flagged
    assert delta_check("creatinine", 130.0, 90.0, 24.0).flagged
    assert not delta_check("creatinine", 95.0, 90.0, 24.0).flagged


def test_derived_findings() -> None:
    found = derive_findings({"temperature": 38.6, "glucose": 2.1, "sbp": 162.0, "hb": 7.1,
                             "creatinine": 180.0}, Patient(47.0, "male", 80.0))
    assert found["find.fever"] and found["find.hypoglycaemia"] and found["find.raised_bp"]
    assert found["find.anaemia"] and found["find.raised_creatinine"]
    assert not derive_findings({"temperature": 37.0}, ADULT)["find.fever"]


def test_scenario_missing_weight_is_reported() -> None:
    from apdt.models.reasoning import ClinicalReasoner

    s = BY_SCENARIO["ao"]
    patient = Patient(s.patient.age_years, s.patient.sex, None, tenant_id="fac-a")
    option = ClinicalReasoner(model()).assess(patient, s.observations, with_tests=False
                                              ).first_option()
    assert option.doses[0].missing == ["weight_kg"]


@pytest.fixture(scope="module")
def trained(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, list]:  # type: ignore[type-arg]
    root = tmp_path_factory.mktemp("apdt-models")
    cases = generate_cohort(500, seed=3)
    from evaluation.models.apdt.train import train_comparator

    train_comparator(cases, root / MODEL_ID, quick=True)
    return root, cases


def test_cohort_cases_are_presentations() -> None:
    cases = generate_cohort(60, seed=5)
    assert len(cases) == 60
    assert all(any(c.observations.findings.values()) or any(c.observations.tests.values())
               for c in cases)
    assert len({c.key for c in cases}) == 60


def test_comparator_and_conformal_sets(trained: tuple[Path, list]) -> None:  # type: ignore[type-arg]
    root, cases = trained
    comparator = Comparator.load(root / MODEL_ID)
    assert comparator is not None
    parts = split_cases(cases)["test"]
    covered = 0
    sizes = []
    for case in parts:
        out = comparator.predict(case.patient, case.observations)
        covered += case.primary in out.conformal_set
        sizes.append(len(out.conformal_set))
        assert out.top in comparator.classes
        assert sum(out.probabilities.values()) == pytest.approx(1.0, abs=1e-4)
    assert covered / len(parts) >= 0.8
    assert 1.0 <= float(np.mean(sizes)) < len(comparator.classes)


def test_bma_weights_sum_to_one() -> None:
    cal = split_cases(generate_cohort(120, seed=9))["cal"][:25]
    weights, info = fit_bma_weights(cal, model())
    assert sum(weights.values()) == pytest.approx(1.0)
    assert set(weights) == set(VARIANTS) and info["n_cases"] > 0
    assert all(0.0 < w < 1.0 for w in weights.values())


def test_train_entry_point_is_importable() -> None:
    assert callable(train)
