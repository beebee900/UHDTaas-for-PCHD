import pytest

from population.cohort import CohortStore, k_min


def case(i, band="45-49"):
    return {"age_band": band, "sex": "female", "state": "Lagos",
            "conditions": ["cond.hypertension"] if i % 2 else [], "bmi": 24.0 + i,
            "name": "dropped", "lga": "dropped"}


def test_k_comes_from_the_kb(kb):
    assert k_min(kb) == 5


def test_records_wait_until_their_class_reaches_k(tmp_path):
    store = CohortStore(tmp_path / "lake", k=5)
    r = store.contribute("cohort_contribution", [case(i) for i in range(3)])
    assert (r.accepted, r.suppressed) == (0, 3) and store.cohort_size() == 0
    r = store.contribute("cohort_contribution", [case(i) for i in range(2)])
    assert (r.accepted, r.suppressed, r.k) == (5, 0, 5)
    r = store.contribute("cohort_contribution", [case(0)])
    assert (r.accepted, r.suppressed) == (1, 0)
    row = store.lake.arrow("contributions").to_pylist()[0]
    assert "name" not in row and "lga" not in row and row["state"] == "Lagos"
    assert CohortStore(tmp_path / "lake", k=5).cohort_size() == 6


def test_small_cells_are_suppressed_in_statistics(tmp_path):
    store = CohortStore(tmp_path / "lake", k=5)
    store.contribute("cohort_contribution", [case(i) for i in range(12)])
    store.contribute("registry_case", [{"condition": "cond.malaria_falciparum", "age_band": "0-4",
                                        "sex": "male", "state": "Lagos", "outcome": "recovered"}
                                       for _ in range(5)])
    counts = {r["condition"]: r["n"] for r in store.condition_counts()}
    assert counts == {"cond.hypertension": 6, "cond.malaria_falciparum": 5}
    store.contribute("cohort_contribution",
                     [{**case(1), "conditions": ["cond.hiv"]} for _ in range(1)])
    counts = {r["condition"]: r["n"] for r in store.condition_counts()}
    assert counts["cond.hiv"] is None


def test_invalid_records_are_refused(tmp_path):
    store = CohortStore(tmp_path / "lake", k=5)
    with pytest.raises(ValueError):
        store.contribute("registry_case", [{"x": 1}])
    with pytest.raises(ValueError):
        store.contribute("cohort_contribution", [case(0, band="47")])
