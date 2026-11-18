import time

import numpy as np
import pytest

from ahdt.models.external import sources
from ahdt.models.external.pbpk import WholeBodyPbpkModel, terminal_half_life_h
from ahdt.models.external.sbml_models import (
    SBML_MODELS,
    BetaCellMassModel,
    CortisolDispositionModel,
    GonadalHormonesModel,
    HepatocyteGlucoseModel,
    MenstrualCycleModel,
)
from atra import contracts as c
from tests.unit.ahdt.models.helpers import HDT

DAY = 86400.0
HOUR = 3600.0


def test_pinned_sources_match_their_hashes():
    for source_id in ("biomodels-341", "biomodels-633", "biomodels-494", "biomodels-916"):
        assert sources.available(source_id), source_id


@pytest.mark.parametrize("cls", SBML_MODELS)
async def test_each_sbml_model_runs_a_scenario_quickly(cls):
    m = cls()
    anatomy = m.spec.instances[0] if m.spec.instances else "atra:sbml"
    record = m.new_record(HDT, anatomy, m.spec.twin)
    started = time.monotonic()
    tr = await m.simulate(record, c.Scenario(kind="intervention"), 30 * DAY, DAY)
    assert time.monotonic() - started < 120
    assert tr.series
    for name, values in tr.series.items():
        assert np.all(np.isfinite(values)), name


async def test_beta_cell_mass_follows_insulin_sensitivity():
    m = BetaCellMassModel()
    p = m.parameters()
    healthy = m.reference_state(p, {})
    resistant = m.reference_state(p, {"insulin_sensitivity": 0.2})
    assert resistant["B"] > healthy["B"]
    assert m.evaluate(p, healthy, {})["beta_cell_mass"] == pytest.approx(healthy["B"])


def test_hepatocyte_releases_glucose_when_blood_glucose_is_low():
    m = HepatocyteGlucoseModel()
    p = m.parameters()
    fasting = m.evaluate(p, {}, {"blood_glucose": 3.0})
    fed = m.evaluate(p, {}, {"blood_glucose": 10.0})
    assert fasting["hepatic_glucose_output"] > fed["hepatic_glucose_output"]


async def test_cortisol_dose_is_conserved_and_cleared():
    m = CortisolDispositionModel()
    record = m.new_record(HDT, "atra:cortisol", m.spec.twin)
    tr = await m.simulate(record, c.Scenario(kind="intervention"), 3 * DAY, 0.5 * DAY)
    total = sum(np.array(v) for v in tr.series.values())
    assert np.allclose(total, total[0], atol=1e-6)
    assert tr.series["cortisol_circulating_fraction"][-1] < 0.01


@pytest.mark.parametrize("cls", [GonadalHormonesModel, MenstrualCycleModel])
async def test_menstrual_cycle_has_two_surges_28_days_apart(cls):
    m = cls()
    record = m.new_record(HDT, "UBERON:0000991", m.spec.twin)
    tr = await m.simulate(record, c.Scenario(kind="intervention"), 70 * DAY, 0.25 * DAY)
    surges = [e.t / DAY for e in tr.events if e.kind == "lh_surge"]
    assert len(surges) >= 2
    assert np.diff(surges).mean() == pytest.approx(28.0, abs=1.4)


def test_cycle_phase_codes():
    m = MenstrualCycleModel()
    out = m.evaluate(m.parameters(), m.initial_state(m.parameters(), {}), {})
    assert out["cycle_phase"] in (1.0, 2.0, 3.0)
    assert out["endometrial_phase"] in (1.0, 2.0)


def pk(model, atc, dose, route, hours=48.0, **inputs):
    scenario = c.Scenario(kind="drug", drug=c.ScenarioDrug(atc=atc, dose_mg=dose, route=route,
                                                           schedule_h=[0.0]))
    record = c.InstanceRecord(instance_id="inst-hdt-000000000000-pk", anatomy="atra:pk",
                              model_id=model.model_id, version=model.version,
                              owner_dt=model.spec.twin, params={},
                              state=model.initial_state(model.parameters(), {}))
    import asyncio

    return asyncio.run(model.simulate(record, scenario, hours * HOUR, 600.0, inputs=inputs))


@pytest.mark.parametrize(("atc", "dose", "route"), [("A10BA02", 500.0, "oral"),
                                                    ("J01DD04", 1000.0, "iv")])
def test_pbpk_conserves_the_dose(atc, dose, route):
    tr = pk(WholeBodyPbpkModel(), atc, dose, route)
    s = tr.series
    total = (np.array(s["amount_in_body"]) + np.array(s["eliminated_amount"])
             + np.array(s["unabsorbed_amount"]))
    assert np.allclose(total[1:], dose, rtol=1e-6)


def test_ceftriaxone_half_life_is_within_the_label_range():
    tr = pk(WholeBodyPbpkModel(), "J01DD04", 1000.0, "iv", hours=60.0)
    t = np.array(tr.t) / HOUR
    half = terminal_half_life_h(t[10:], np.array(tr.series["plasma_concentration"])[10:])
    assert 5.8 <= half <= 8.7  # label: 5.8 to 8.7 h


def test_pbpk_metformin_peaks_after_oral_dosing_and_clears_through_the_kidney():
    tr = pk(WholeBodyPbpkModel(), "A10BA02", 500.0, "oral", hours=72.0)
    conc = np.array(tr.series["plasma_concentration"])
    peak_h = tr.t[int(np.argmax(conc))] / HOUR
    assert 1.0 <= peak_h <= 4.0
    assert tr.series["eliminated_amount"][-1] > 0.4 * 500.0 * 0.55 * 0.9


def test_reduced_egfr_slows_metformin_clearance():
    normal = pk(WholeBodyPbpkModel(), "A10BA02", 500.0, "oral", hours=24.0)
    impaired = pk(WholeBodyPbpkModel(), "A10BA02", 500.0, "oral", hours=24.0, egfr=30.0)
    assert impaired.series["plasma_concentration"][-1] > normal.series["plasma_concentration"][-1]
