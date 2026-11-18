import pytest

from population.demography import GROUPS, project


def test_projection_ages_the_cohort():
    base = {g: {"female": 1000.0, "male": 1000.0} for g in GROUPS}
    steps = project(base, steps=2)
    assert [s["year"] for s in steps] == [0.0, 5.0, 10.0]
    assert steps[0]["total"] == pytest.approx(2000.0 * len(GROUPS))
    assert steps[1]["by_group"]["5-9"]["female"] < 1000.0
    assert steps[1]["by_group"]["0-4"]["male"] > steps[1]["by_group"]["0-4"]["female"]
    assert all(s["dependency_ratio"] > 0 for s in steps)
