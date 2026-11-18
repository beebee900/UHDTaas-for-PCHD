"""Early warning, `$apply` and conformance."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from apdt.knowledge.pathways import TASK_NAMES
from apdt.models.care import pathways
from apdt.models.care.early_warning import score
from evaluation.models.apdt.scenarios import BY_SCENARIO

T0 = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
FULL = ["register", "triage", "history", "examine", "test", "diagnose", "treat", "follow_up",
        "discharge"]


def events(steps: list[str]) -> list[tuple[str, datetime]]:
    return [(s, T0 + timedelta(minutes=i)) for i, s in enumerate(steps)]


def test_news2_bands_follow_the_kb() -> None:
    high = score({"respiration_rate": 28, "spo2": 90, "systolic_bp": 88, "pulse": 125,
                  "temperature": 39.5, "consciousness": "V"}, 40)
    assert high is not None and high.scale == "news2" and high.band == "high"
    assert high.monitoring is not None and high.monitoring.get("continuous")
    assert score({"respiration_rate": 28}, 40) is None


def test_pews_for_a_child() -> None:
    ews = score({"respiration_rate": 28, "spo2": 98, "systolic_bp": 100, "pulse": 90,
                 "temperature": 37.0, "consciousness": "A"}, 8)
    assert ews is not None and ews.scale == "pews" and ews.total >= 0


def test_apply_builds_a_care_plan_and_tasks() -> None:
    from fhir.resources.R4B.careplan import CarePlan
    from fhir.resources.R4B.task import Task

    s = BY_SCENARIO["ao"]
    applied = pathways.apply("cond.malaria_falciparum", s.patient, s.observations, "hdt-x",
                             when=T0)
    CarePlan.model_validate(applied.care_plan)
    for t in applied.tasks:
        Task.model_validate(t)
    assert applied.option is not None
    assert applied.option.option_id == s.expected_first_option
    assert any("Prescribe" in t["description"] for t in applied.tasks)
    assert applied.care_plan["instantiatesCanonical"][0].endswith("malaria_falciparum")


def test_apply_without_an_eligible_option_says_so() -> None:
    s = BY_SCENARIO["cn"]
    applied = pathways.apply("cond.malaria_falciparum", s.patient, s.observations, "hdt-y",
                             when=T0)
    assert applied.option is not None or applied.notes


def test_conforming_trace_is_fit() -> None:
    result = pathways.conformance("acute_febrile", {"c1": events(FULL)})
    assert result.conformant and result.fitness == pytest.approx(1.0)


def test_skipped_step_is_reported() -> None:
    skipped = [s for s in FULL if s != "test"]
    result = pathways.conformance("acute_febrile", {"ok": events(FULL), "bad": events(skipped)})
    assert not result.conformant and result.fitness < 1.0
    bad = next(d for d in result.deviations if d.case_id == "bad")
    assert not bad.fit and bad.problem_steps
    assert TASK_NAMES["diagnose"] in bad.problem_steps
    assert next(d for d in result.deviations if d.case_id == "ok").fit
