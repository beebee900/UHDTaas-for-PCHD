"""Background jobs of the slow external simulators as durable workflows (design 08, WP14c).

The jobs run through the `WorkflowBackend`: `MemoryWorkflows` in profile p0 and Temporal in
the container profiles. Each job is one activity, so a restarted run takes a finished result
from the workflow store instead of running the simulator again. Arguments and results are
JSON values; a pose track is passed as the path of an `.npz` file written by `save_track`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import numpy as np

from ahdt.models.external import opencarp, opensim_gait, sources
from ahdt.models.params import load_params, params_path
from atra.backends.base import WorkflowBackend, WorkflowContext
from edge.devices.decode.gait import PoseTrack

OPENCARP_WORKFLOW = "ahdt.models.opencarp_tissue"
OPENSIM_WORKFLOW = "ahdt.models.opensim_gait"


def job_directory(kind: str, run_id: str) -> Path:
    return sources.directory().parent / "jobs" / kind / run_id


def save_track(track: PoseTrack, path: Path) -> Path:
    np.savez_compressed(path, fps=track.fps, image=track.image, world=track.world)
    return path


def load_track(path: Path) -> PoseTrack:
    with np.load(path) as data:
        return PoseTrack(float(data["fps"]), data["image"], data["world"])


async def _tissue(heart_rate: float, ikr_block: float, run_id: str) -> dict[str, Any]:
    p = load_params(params_path(opencarp.__file__, "opencarp")).values
    scenario = opencarp.TissueScenario(heart_rate=heart_rate, ikr_block=ikr_block)
    result = await asyncio.to_thread(opencarp.run_job, p, scenario,
                                     job_directory("opencarp", run_id))
    return {**opencarp.CardiacElectrophysiologyModel.values_of(result),
            "activated_fraction": result.activated_fraction, "runtime_s": result.runtime_s,
            "mesh_json": str(result.mesh_json), "mesh_vtk": str(result.mesh_vtk)}


async def _gait(track_path: str, muscles: bool, run_id: str) -> dict[str, Any]:
    cls = (opensim_gait.SkeletalMuscleModel if muscles
           else opensim_gait.BiomechanicalKinematicModel)
    model = cls()
    track = await asyncio.to_thread(load_track, Path(track_path))
    values = await asyncio.to_thread(
        model.evaluate, model.parameters(), model.initial_state(model.parameters(), {}),
        {"pose_track": track, "job_id": run_id})
    return {"model_id": model.model_id, "values": {k: float(v) for k, v in values.items()},
            "directory": str(job_directory("opensim", run_id))}


async def opencarp_tissue(ctx: WorkflowContext, heart_rate: float = 60.0,
                          ikr_block: float = 0.0) -> dict[str, Any]:
    result: dict[str, Any] = await ctx.activity(_tissue, heart_rate, ikr_block, ctx.run_id)
    return result


async def opensim_gait_job(ctx: WorkflowContext, track_path: str,
                           muscles: bool = True) -> dict[str, Any]:
    result: dict[str, Any] = await ctx.activity(_gait, track_path, muscles, ctx.run_id)
    return result


def register(workflows: WorkflowBackend) -> None:
    workflows.register(OPENCARP_WORKFLOW, opencarp_tissue)
    workflows.register(OPENSIM_WORKFLOW, opensim_gait_job)
