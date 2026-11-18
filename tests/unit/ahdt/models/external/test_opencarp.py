import json

import numpy as np
import pytest

from ahdt.models.external import backends, baselines, opencarp
from ahdt.models.params import load_params, params_path

pytestmark = pytest.mark.skipif(not backends.opencarp().available, reason="openCARP is missing")


@pytest.fixture(scope="module")
def params():
    return load_params(params_path(opencarp.__file__, "opencarp")).values


def test_parameter_file_applies_the_scenario(params, tmp_path):
    scenario = opencarp.TissueScenario(heart_rate=75.0, ikr_block=0.5)
    text = opencarp.parameter_file(params, scenario, tmp_path / "slab", "out")
    assert "imp_region[0].im = tenTusscherPanfilov" in text
    assert "imp_region[0].im_param = GKr*0.5" in text
    assert "stim[0].ptcl.bcl = 800" in text
    plain = opencarp.parameter_file(params, opencarp.TissueScenario(), tmp_path / "slab", "out")
    assert "im_param" not in plain


def test_igb_reader_round_trip(tmp_path):
    data = np.arange(12, dtype="<f4").reshape(3, 4)
    header = "x:4 y:1 z:1 t:3 type:float inc_t:2 dim_t:4 unites_t:ms"
    path = tmp_path / "v.igb"
    path.write_bytes(header.ljust(opencarp.IGB_HEADER).encode("ascii") + data.tobytes())
    values, dt = opencarp.read_igb(path)
    assert dt == 2.0
    assert np.array_equal(values, data)


def test_ikr_block_scenario_runs_in_two_minutes_and_prolongs_repolarisation(params, tmp_path):
    result = opencarp.run_job(params, opencarp.TissueScenario(ikr_block=0.5), tmp_path)
    assert result.runtime_s < 120
    assert result.activated_fraction == 1.0
    assert 0.3 < result.conduction_velocity_m_s < 0.9
    control = opencarp.single_cell_apd90(params, opencarp.TissueScenario())
    assert result.apd90_ms > control
    assert result.apd90_ms == pytest.approx(
        opencarp.single_cell_apd90(params, opencarp.TissueScenario(ikr_block=0.5)), rel=0.05)
    mesh = json.loads(result.mesh_json.read_text())
    assert len(mesh["points"]) == len(mesh["pointData"]["activation_ms"])
    assert mesh["polys"]
    assert result.mesh_vtk.read_text().startswith("# vtk DataFile Version 3.0")


def test_baseline_matches_the_current_parameters(params):
    model = opencarp.CardiacElectrophysiologyModel()
    cached = baselines.lookup(model.model_id, model.parameters(), {})
    assert cached is not None
    assert cached["state"]["apd90"] == pytest.approx(
        opencarp.single_cell_apd90(params, opencarp.TissueScenario()), rel=0.05)
