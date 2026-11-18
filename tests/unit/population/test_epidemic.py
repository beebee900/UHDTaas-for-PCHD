import math

import pytest

from population.epidemic import (
    CovasimRespiratory,
    Intervention,
    RespiratoryScenario,
    RossMacdonald,
    compare,
    target_prevalence,
)


@pytest.fixture(scope="module")
def malaria():
    return RossMacdonald()


def test_calibrated_to_the_kb_prevalence(malaria, kb):
    assert target_prevalence(kb) == pytest.approx(0.034)
    summary = malaria.run(Intervention()).summary()
    assert summary["mean_prevalence"] == pytest.approx(0.034, rel=0.02)
    assert summary["rainy_prevalence"] > summary["dry_prevalence"]


def test_reproductive_number_matches_the_formula(malaria):
    k = malaria.rates(Intervention())
    m = malaria.mean_density(malaria.m_rainy)
    r0 = m * k.a ** 2 * k.b * k.c * math.exp(-k.g * k.v) / (k.g * k.r)
    x, z = malaria.equilibrium(m, k)
    assert r0 > 1 and x == pytest.approx((r0 - 1) / (r0 + k.a * k.c / k.g))
    assert 0 < z < math.exp(-k.g * k.v)


def test_interventions_lower_transmission(malaria):
    out = compare(malaria, {"nets": Intervention(bednet_coverage=0.6),
                            "vaccine": Intervention(vaccine_coverage=0.5),
                            "treatment": Intervention(treatment_coverage=0.3)})
    base = out["baseline"]
    for name in ("nets", "vaccine", "treatment"):
        assert out[name]["mean_prevalence"] < base["mean_prevalence"]
        assert out[name]["mean_reproductive_number"] < base["mean_reproductive_number"]
        assert 0 < out[name]["prevalence_reduction"] <= 1
    with pytest.raises(ValueError):
        Intervention(bednet_coverage=1.5)


def test_covasim_testing_and_tracing_scenario():
    model = CovasimRespiratory(pop_size=1000)
    out = compare(model, {"test_trace": RespiratoryScenario(test_prob=0.3, trace_prob=0.5)},
                  days=60)
    assert out["test_trace"]["mean_prevalence"] <= out["baseline"]["mean_prevalence"]
