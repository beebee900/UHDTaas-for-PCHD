"""The six persona scenarios through the core reasoning chain."""

from __future__ import annotations

from functools import cache, lru_cache

import pytest

from apdt.models.reasoning import Assessment, ClinicalReasoner
from evaluation.models.apdt.scenarios import SCENARIOS, Scenario


@lru_cache(maxsize=1)
def reasoner() -> ClinicalReasoner:
    return ClinicalReasoner()


@cache
def assessed(key: str) -> Assessment:
    s = next(x for x in SCENARIOS if x.key == key)
    return reasoner().assess(s.patient, s.observations)


@pytest.mark.parametrize("s", SCENARIOS, ids=lambda s: s.key)
def test_top_diagnosis(s: Scenario) -> None:
    a = assessed(s.key)
    top = a.differential.top()
    assert top is not None
    assert top.condition == s.expected_top
    ranked = [c.condition for c in a.differential.candidates]
    for extra in s.extra_top:
        assert extra in ranked[:3]


@pytest.mark.parametrize("s", SCENARIOS, ids=lambda s: s.key)
def test_first_option_is_guideline_concordant(s: Scenario) -> None:
    option = assessed(s.key).first_option()
    assert option is not None
    assert option.option_id == s.expected_first_option
    assert option.citations
    assert option.preference == "first_line"
    assert all(d.structured or d.raw for d in option.doses)


@pytest.mark.parametrize("s", SCENARIOS, ids=lambda s: s.key)
def test_expected_safety_issues(s: Scenario) -> None:
    a = assessed(s.key)
    ids = {i.ix_id for i in a.issues}
    assert set(s.expected_issues) <= ids
    for issue in a.issues:
        assert issue.detected_issue["resourceType"] == "DetectedIssue"
        assert issue.blocks_signing == (issue.severity == "high")


def test_pregnancy_changes_options() -> None:
    a = assessed("cn")
    cond = "cond.pyelonephritis"
    eligible = {o.option_id for o in a.options[cond].eligible}
    assert "tx.pyelonephritis.pregnancy.ceftriaxone" in eligible
    assert "tx.pyelonephritis.adult_mild.ciprofloxacin" not in eligible
    assert a.options[cond].severity == "severe"


def test_severe_malaria_excludes_pre_referral_for_age_eight() -> None:
    a = assessed("bm")
    s = a.options["cond.malaria_falciparum"]
    assert s.severity == "severe"
    assert "tx.malaria.severe.prereferral_rectal_artesunate" in {i.option_id for i in s.ineligible}
    dose = s.eligible[0].doses[0]
    assert dose.per_dose["mg"] == pytest.approx(2.4 * 25.0)


def test_uncomplicated_malaria_dose_is_weight_banded() -> None:
    dose = assessed("ao").first_option().doses[0]
    assert dose.per_dose["mg"] == {"artemether": 80, "lumefantrine": 480}
    assert not dose.issues


def test_tb_art_interaction_blocks_signing() -> None:
    a = assessed("gh")
    blocking = [i for i in a.issues if i.ix_id == "ix.dolutegravir.rifampicin"]
    assert blocking and blocking[0].blocks_signing and blocking[0].queue == "pharmacist"
    option = a.first_option()
    assert any(adj["source"] == "ix.dolutegravir.rifampicin" for adj in option.adjustments)


def test_ckd_patient_egfr_is_derived() -> None:
    a = assessed("de")
    assert a.patient.egfr is not None and 30 <= a.patient.egfr < 45


def test_news2_is_computed_for_adults() -> None:
    from apdt.models.care.early_warning import score
    ew = score({"respiration_rate": 16, "spo2": 97, "systolic_bp": 120, "pulse": 70,
                "temperature": 36.8, "consciousness": "A"}, 40)
    assert ew is not None and ew.scale == "news2" and ew.total == 0


def test_assess_scores_news2_from_the_intake_field_names() -> None:
    from dataclasses import replace

    from apdt.services.views import intake_catalogue
    from atra.config import ROOT

    s = next(x for x in SCENARIOS if x.key == "ao")
    fields = {m.field for m in intake_catalogue(ROOT / "kb").measurements}
    vitals = {"respiratory_rate": 28, "spo2": 90, "sbp": 88, "heart_rate": 128,
              "temperature": 39.4}
    assert set(vitals) <= fields
    obs = replace(s.observations, measurements={**s.observations.measurements, **vitals},
                  avpu="V")
    ew = reasoner().assess(s.patient, obs, with_tests=False).early_warning
    assert ew is not None and ew.scale == "news2" and ew.components["respiration_rate"] == 3
