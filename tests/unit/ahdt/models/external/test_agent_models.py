import time

import numpy as np
import pytest

from ahdt.models.external import immune_abm, mobility_abm
from ahdt.models.external.agent_models import ImmuneResponseModel, MobilityModel
from atra import contracts as c
from tests.unit.ahdt.models.helpers import HDT

DAY = 86400.0


async def test_immune_response_clears_antigen_and_leaves_memory():
    m = ImmuneResponseModel()
    record = m.new_record(HDT, "UBERON:0002465", m.spec.twin)
    scenario = c.Scenario(kind="intervention", environment={"antigen_load": 20.0})
    started = time.monotonic()
    tr = await m.simulate(record, scenario, 16 * DAY, DAY)
    assert time.monotonic() - started < 120
    s = {k: np.array(v) for k, v in tr.series.items()}
    assert s["antigen"].max() > 100 and s["antigen"][-1] == 0.0
    peak_day = int(np.argmax(s["effector_t_cells"]))
    assert 2 <= peak_day <= 10
    assert s["effector_t_cells"][-1] < s["effector_t_cells"].max()
    assert s["memory_t_cells"][-1] > 0
    assert s["antibody"][-1] > s["antibody"][peak_day]
    assert [e.kind for e in tr.events] == ["effector_peak"]


def test_immune_run_is_repeatable():
    m = ImmuneResponseModel()
    p = m.parameters()
    a = m.run_days(p, m.initial_state(p, {}), {"antigen_load": 20.0}, 4.0, 1.0)
    b = m.run_days(p, m.initial_state(p, {}), {"antigen_load": 20.0}, 4.0, 1.0)
    assert [r.effector_t for r in a] == [r.effector_t for r in b]


def test_memory_cells_answer_a_second_exposure_faster():
    m = ImmuneResponseModel()
    p = m.parameters()
    naive = immune_abm.run(p, 3, 20.0, 5.0, 24)
    primed = immune_abm.run(p, 3, 20.0, 5.0, 24, {"memory_t": 150.0, "naive_t": 850.0})
    assert primed[2].effector_t > naive[2].effector_t


async def test_mobility_explores_and_returns():
    m = MobilityModel()
    record = m.new_record(HDT, "atra:mobility", m.spec.twin)
    tr = await m.simulate(record, c.Scenario(kind="activity"), 90 * DAY, 7 * DAY)
    locations = np.array(tr.series["distinct_locations"])
    assert np.all(np.diff(locations) >= 0)
    assert locations[-1] > 5
    assert tr.series["top_location_share"][-1] < 0.6


def test_mobility_fit_recovers_the_generating_parameters():
    m = MobilityModel()
    p = m.parameters()
    model = mobility_abm.MobilityModel(p, seed=11)
    for _ in range(24 * 365 * 4):
        model.step()
    trace = np.array(next(iter(model.agents)).trace)
    fit = mobility_abm.fit_trace(trace[:, 0], trace[:, 1:], tolerance_km=1e-6)
    assert fit.rho == pytest.approx(p["rho"], abs=0.12)
    assert fit.gamma == pytest.approx(p["gamma"], abs=0.12)
