import time

import numpy as np
import pytest

from ahdt.models.external import backends, opensim_gait
from ahdt.models.params import load_params, params_path
from tests.unit.ahdt.models.helpers import HDT

pytestmark = pytest.mark.skipif(not backends.opensim().available, reason="OpenSim is missing")

PERIOD = 1.1


@pytest.fixture(scope="module")
def params():
    return load_params(params_path(opensim_gait.__file__, "opensim")).values


@pytest.fixture(scope="module")
def track(params):
    return opensim_gait.model_track(params, seconds=3 * PERIOD, period_s=PERIOD)


def test_model_facts(params):
    model = opensim_gait.build_model(params)
    assert model.getCoordinateSet().getSize() == 23
    assert model.getMarkerSet().getSize() == 10
    assert model.getTotalMass(model.initSystem()) == pytest.approx(75.16, abs=0.1)


def test_kinematics_recover_the_pose_that_made_the_markers(params, track, tmp_path):
    pose, truth = track
    started = time.monotonic()
    a = opensim_gait.analyse(pose, params, tmp_path, seconds=3 * PERIOD, muscles=False)
    assert time.monotonic() - started < 120
    assert a.marker_rms_m < 0.005
    assert opensim_gait._knee_peak(a) == pytest.approx(truth["knee_flexion_peak"], abs=3.0)
    assert a.range("hip_flexion_r") > 20.0


def test_muscle_forces_are_estimated_for_the_stride(params, track, tmp_path):
    pose, _ = track
    started = time.monotonic()
    a = opensim_gait.analyse(pose, params, tmp_path, seconds=3 * PERIOD, muscles=True)
    assert time.monotonic() - started < 120
    weight = a.mass_kg * opensim_gait.GRAVITY
    assert np.mean(a.grf_vertical_n) == pytest.approx(weight, rel=0.05)
    assert a.group_peak(opensim_gait.QUADRICEPS) > 0
    assert a.group_peak(opensim_gait.PLANTARFLEXORS) > 0
    assert np.isfinite(a.reserve_force_n)
    assert all(np.all(np.isfinite(v)) for v in a.muscle_force_n.values())


async def test_wrappers_return_their_declared_outputs(track):
    pose, _ = track
    for cls in (opensim_gait.BiomechanicalKinematicModel, opensim_gait.SkeletalMuscleModel):
        m = cls()
        out = await m.predict({"pose_track": pose, "hdt_id": HDT}, None)
        assert set(out.values) == {p.name for p in m.spec.outputs}
        assert out.values["marker_rms_error"] < 0.01
