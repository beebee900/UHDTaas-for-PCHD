import pytest

from ahdt.models.reference import default_kb
from ahdt.models.whole_body.early_warning import EarlyWarningModel, range_score


@pytest.fixture(scope="module")
def model() -> EarlyWarningModel:
    return EarlyWarningModel(kb=default_kb())


def run(model: EarlyWarningModel, **inputs):
    return model.evaluate(model.parameters(), {}, inputs)


def test_news2_adult_medium_band(model):
    out = run(model, age=47, respiration_rate=22, spo2=95, spo2_scale=1, on_oxygen=False,
              systolic_bp=105, pulse=95, consciousness="alert", temperature=38.5)
    # RR 21-24 → 2, SpO2 94-95 → 1, SBP 101-110 → 1, pulse 91-110 → 1, temp 38.1-39.0 → 1.
    assert out["news2"] == 6
    assert out["news2_band"] == "medium"


def test_news2_single_red_parameter(model):
    out = run(model, age=30, respiration_rate=16, spo2=97, spo2_scale=1, on_oxygen=False,
              systolic_bp=120, pulse=70, consciousness="new_confusion", temperature=37.0)
    assert out["news2"] == 3
    assert out["news2_band"] == "low_medium"


def test_pews_school_age_child(model):
    # Persona B.M., 8 years: 5 to 12 years chart.
    out = run(model, age=8, respiration_rate=32, pulse=150, systolic_bp=100, spo2=93)
    assert out["pews_respiration_rate"] == 1
    assert out["pews_heart_rate"] == 2
    assert out["pews_systolic_bp"] == 0
    assert out["pews_spo2"] == 1
    assert out["pews"] == 4
    assert out["pews_level"] == "low"
    assert "news2" not in out


def test_pews_trigger_raises_the_level(model):
    out = run(model, age=8, respiration_rate=22, pulse=100, systolic_bp=100, spo2=97,
              pews_triggers=["avpu_voice"])
    assert out["pews"] == 0
    assert out["pews_level"] == "high"


def test_pews_infant_and_oxygen(model):
    out = run(model, age=0.5, respiration_rate=65, pulse=120, systolic_bp=80, spo2=96,
              oxygen_flow=4, respiratory_distress="moderate")
    # RR 60-70 → 2, flow 2-6 L/min → 2, moderate distress → 2.
    assert out["pews"] == 6
    assert out["pews_level"] == "medium"


def test_boundary_takes_the_higher_band():
    bands = [{"max": 120, "score": 0}, {"min": 120, "max": 140, "score": 1},
             {"min": 140, "score": 2}]
    assert range_score(140, bands) == 2
    assert range_score(130, bands) == 1


def test_gap_between_bands_takes_the_higher_neighbour():
    spo2 = [{"min": 95, "score": 0}, {"min": 92, "max": 94, "score": 1}, {"max": 91, "score": 4}]
    assert range_score(91.5, spo2) == 4
    assert range_score(94.5, spo2) == 1
