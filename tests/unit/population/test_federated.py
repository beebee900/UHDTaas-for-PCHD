import pytest

from population.federated import (
    BudgetExceeded,
    PrivacyLedger,
    TenantClient,
    round_cost,
    run_round,
)
from tests.unit.population.conftest import person_frames

CONDS = ["cond.hypertension", "cond.diabetes_type2"]


def tenant_rows(seed):
    persons, _, _ = person_frames(400, seed)
    return persons.assign(season="all")


def test_one_federated_round_with_dp_accounting(priors, kb):
    """Acceptance: one round completes and reports the privacy spend per tenant."""
    ledger = PrivacyLedger.from_kb(kb)
    before = priors.prior("cond.hypertension", "40-59", "female", "dry", "north_west")
    clients = [TenantClient("fac-a", tenant_rows(11)), TenantClient("fac-b", tenant_rows(12))]
    report = run_round(priors, clients, CONDS, ledger, epsilon=1.0, seed=5)
    assert report.round == 1 and report.tenants == ["fac-a", "fac-b"]
    assert report.epsilon_spent == {"fac-a": 4.0, "fac-b": 4.0}
    assert report.epsilon_remaining == {"fac-a": 16.0, "fac-b": 16.0}
    assert report.cells > 0 and report.persons == pytest.approx(800, rel=0.1)
    after = priors.prior("cond.hypertension", "40-59", "female", "dry", "north_west")
    assert after.source == "federated round 1 (epsilon 1.0 per cell)"
    assert after.prevalence != before.prevalence
    assert priors.rounds == 1


def test_the_ledger_refuses_a_round_over_budget(priors):
    ledger = PrivacyLedger(budget=5.0)
    clients = [TenantClient("fac-a", tenant_rows(13))]
    run_round(priors, clients, CONDS, ledger, epsilon=1.0)
    with pytest.raises(BudgetExceeded):
        run_round(priors, clients, CONDS, ledger, epsilon=1.0)
    assert ledger.spent("fac-a") == 4.0 and priors.rounds == 1


def test_composition():
    assert round_cost(0.5, 3) == 3.0
    assert round_cost(1.0, 1, records_per_person=12) == 24.0
