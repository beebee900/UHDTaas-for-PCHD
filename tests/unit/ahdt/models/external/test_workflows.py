import pytest

from ahdt.models.external import backends, opensim_gait, workflows
from ahdt.models.params import load_params, params_path
from atra.backends.memory import MemoryWorkflows


@pytest.mark.skipif(not backends.opencarp().available, reason="openCARP is missing")
async def test_opencarp_runs_as_a_background_job():
    wf = MemoryWorkflows()
    workflows.register(wf)
    run_id = await wf.start(workflows.OPENCARP_WORKFLOW, {"heart_rate": 60.0, "ikr_block": 0.0})
    result = await wf.result(run_id, timeout_s=300)
    run = await wf.status(run_id)
    assert run.status == "completed"
    assert result["apd90"] > 250
    assert result["runtime_s"] < 120
    assert result["mesh_vtk"].endswith("tissue.vtk")
    await wf.close()


@pytest.mark.skipif(not backends.opensim().available, reason="OpenSim is missing")
async def test_opensim_runs_as_a_background_job(tmp_path):
    p = load_params(params_path(opensim_gait.__file__, "opensim")).values
    track, _ = opensim_gait.model_track(p, seconds=3.3, period_s=1.1)
    path = workflows.save_track(track, tmp_path / "track.npz")
    wf = MemoryWorkflows()
    workflows.register(wf)
    run_id = await wf.start(workflows.OPENSIM_WORKFLOW,
                            {"track_path": str(path), "muscles": False})
    result = await wf.result(run_id, timeout_s=300)
    assert result["model_id"] == "ahdt.whole_body.biomechanical_and_kinematic"
    assert result["values"]["marker_rms_error"] < 0.01
    await wf.close()


def test_track_round_trip(tmp_path):
    p = load_params(params_path(opensim_gait.__file__, "opensim")).values
    if not backends.opensim().available:
        pytest.skip("OpenSim is missing")
    track, _ = opensim_gait.model_track(p, seconds=0.5)
    again = workflows.load_track(workflows.save_track(track, tmp_path / "t.npz"))
    assert again.fps == track.fps
    assert again.world.shape == track.world.shape
