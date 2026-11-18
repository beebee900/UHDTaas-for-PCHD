"""The policy tree distilled from the test-selection policy."""

from __future__ import annotations

from pathlib import Path

from apdt.models.context import Observations, Patient
from apdt.models.diagnosis.distilled import MODEL_ID, PolicyTree
from apdt.models.diagnosis.tests_select import price_list
from evaluation.models.apdt.cohort import generate_cohort
from evaluation.models.apdt.distill import distill

PATIENT = Patient(35.0, "male", 70.0, tenant_id="fac-b")
OBS = Observations(findings={"find.fever": True, "find.cough": True, "find.weight_loss": True,
                             "find.headache": True})


def test_distilled_tree_follows_the_policy(tmp_path: Path) -> None:
    result = distill(generate_cohort(150, seed=4), tmp_path, max_depth=4)
    assert 0.0 <= result.value <= 1.0
    tree = PolicyTree.load(tmp_path)
    assert tree is not None
    assert tree.next_test(PATIENT, OBS) in tree.spec["classes"]
    assert tree.rules()
    assert (tmp_path / MODEL_ID / "metrics.json").exists()
    assert result.metrics["fidelity"] >= result.metrics["majority_baseline"] - 0.05


def test_unknown_tenant_has_no_prices() -> None:
    assert price_list("no-such-tenant") == {}
