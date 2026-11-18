from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from ahdt.models.digestive.absorption import AbsorptionModel
from ahdt.models.endocrine.glucose_insulin import GlucoseInsulinModel, MinimalModel
from atra import contracts as c
from tests.unit.ahdt.models.helpers import HDT, observation

# FSIGT of a normal subject: Pacini and Bergman (1986), as tabulated in Knott's MLAB note.
FSIGT_T = [0, 2, 4, 6, 8, 10, 12, 14, 16, 19, 22, 27, 32, 42, 52, 62, 72, 82, 92, 102, 122,
           142, 162, 182]
FSIGT_G = [92, 350, 287, 251, 240, 216, 211, 205, 196, 192, 172, 163, 142, 124, 105, 92, 84,
           77, 82, 81, 82, 82, 85, 90]
FSIGT_I = [11, 26, 130, 85, 51, 49, 45, 41, 35, 30, 30, 27, 30, 22, 15, 15, 11, 10, 8, 11, 7, 8,
           8, 7]


def test_minimal_model_reproduces_the_published_fsigt_fit():
    fit = MinimalModel().fit_glucose(FSIGT_T, FSIGT_G, FSIGT_I, g0=287)
    # Published least-squares estimates: p1 0.0314, p2 0.0188, p3 9.49e-6.
    assert fit.p1 == pytest.approx(0.03139866193, rel=0.05)
    assert fit.p2 == pytest.approx(0.01877500745, rel=0.10)
    assert fit.p3 == pytest.approx(9.491576611e-06, rel=0.10)
    assert fit.insulin_sensitivity == pytest.approx(5.05543161e-4, rel=0.10)


async def test_minimal_model_returns_to_basal():
    m = MinimalModel()
    record = m.new_record(HDT, "UBERON:0001264", m.spec.twin)
    tr = await m.simulate(record, c.Scenario(kind="intervention"), 180 * 60, 60)
    g = tr.series["glucose_mgdl"]
    assert g[0] == pytest.approx(m.base_params()["G_0"])
    assert abs(g[-1] - m.base_params()["G_b"]) < 15


async def test_dalla_man_holds_basal_without_a_meal():
    m = GlucoseInsulinModel()
    record = m.new_record(HDT, "UBERON:0001264", m.spec.twin)
    tr = await m.simulate(record, c.Scenario(kind="diet"), 7 * 3600, 600)
    g = np.array(tr.series["glucose_mgdl"])
    assert g[0] == pytest.approx(95.0)
    assert np.all(np.abs(g - 95.0) < 0.05 * 95.0)


async def test_dalla_man_meal_appearance_conserves_the_absorbed_fraction():
    m = GlucoseInsulinModel()
    record = m.new_record(HDT, "UBERON:0001264", m.spec.twin)
    meal = c.Scenario(kind="diet", diet={"meals": [{"t_s": 0, "carbs_g": 78}]})
    tr = await m.simulate(record, meal, 12 * 3600, 60)
    ra = np.array(tr.series["Ra"])
    appeared_g = np.trapezoid(ra, np.array(tr.t) / 60.0) * m.base_params()["BW"] / 1000.0
    assert appeared_g == pytest.approx(0.9 * 78, rel=0.02)
    g = np.array(tr.series["glucose_mgdl"])
    assert g.max() > 130 and 30 * 60 <= tr.t[int(g.argmax())] <= 120 * 60
    assert tr.events[0].kind == "glucose_peak"
    assert tr.units["glucose"] == "mmol/L"


async def test_dalla_man_uses_a_coupled_appearance_rate():
    m = GlucoseInsulinModel()
    record = m.new_record(HDT, "UBERON:0001264", m.spec.twin)
    tr = await m.simulate(record, c.Scenario(kind="diet"), 3600, 600, inputs={"Ra": 5.0})
    assert tr.series["glucose_mgdl"][-1] > 120


async def test_dalla_man_calibration_moves_towards_observed_glucose():
    m = GlucoseInsulinModel()
    t0 = datetime(2026, 10, 1, 8, tzinfo=UTC)
    record = m.new_record(HDT, "UBERON:0001264", m.spec.twin).model_copy(
        update={"last_assimilated": t0})
    inputs = {"meals": [{"t_s": 0, "carbs_g": 78}]}
    truth = m.parameters() | {"V_mX": 0.047 * 0.5, "k_p3": 0.009 * 0.5}
    times = np.arange(0, 6 * 60 + 1, 15.0)
    _, series = m.run(truth, m.vector(record.state, truth, inputs), times, m.drive(None, inputs),
                      impulses=m.impulses(None, inputs))
    obs = [observation("15074-8", float(v), "mmol/L", t0 + timedelta(minutes=float(t)))
           for t, v in zip(times[1:], series["glucose"][1:], strict=True)]
    fitted = await m.calibrate(record, obs, inputs=inputs)
    assert fitted.params["V_mX"] < 0.047
    assert fitted.uncertainty["V_mX"]["std"] > 0
    assert fitted.last_assimilated == obs[-1].effective_time


async def test_absorption_model_drug_and_meal():
    m = AbsorptionModel()
    record = m.new_record(HDT, "UBERON:0000160", m.spec.twin)
    scenario = c.Scenario(kind="drug", drug=c.ScenarioDrug(atc="P01BF01", dose_mg=480,
                                                           route="oral", schedule_h=[0]),
                          diet={"meals": [{"t_s": 0, "carbs_g": 50}]})
    tr = await m.simulate(record, scenario, 4 * 3600, 600, inputs={"ka": 0.6})
    assert tr.series["drug_absorption_rate"][0] == pytest.approx(480 * 0.6)
    assert tr.series["stomach_content"][0] == pytest.approx(50_000)
    assert tr.series["stomach_content"][-1] < 50_000


async def test_predict_returns_a_model_output():
    m = GlucoseInsulinModel()
    record = m.new_record(HDT, "UBERON:0001264", m.spec.twin)
    out = await m.predict({}, record)
    assert out.hdt_id == HDT
    assert out.values["glucose"] == pytest.approx(95 * 0.0555, rel=0.01)
    assert out.inputs_ref.startswith("inputs:")
