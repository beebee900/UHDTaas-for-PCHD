"""Phone video → pose landmarks → gait features → AHDT Layer 3 (design 04, 4.1.1)."""

import importlib.util
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from ahdt.devices.sink import EdgeSink
from ahdt.ingest import build_pipeline
from ahdt.ingest.fields import field_index
from atra.backends import Backends
from atra.config import ROOT, Settings
from atra.consent import demo_registry
from atra.personas import PERSONAS
from atra.provenance import AuditLog
from edge.devices.decode import gait
from edge.devices.gateway import DeviceGateway
from edge.devices.sim import TruthStream, phone

HDT = PERSONAS[0].hdt_id
START = datetime(2026, 10, 10, 8, tzinfo=UTC)
FIELD = "urn:atra:field"
MODEL = ROOT / "var" / "datasets" / "mediapipe-pose-lite" / "pose_landmarker_lite.task"
CLIP = next((ROOT / "var" / "datasets" / "yoon-2012-treadmill").glob("*.ogv"), None) \
    if (ROOT / "var" / "datasets" / "yoon-2012-treadmill").exists() else None
needs_pose = pytest.mark.skipif(
    importlib.util.find_spec("mediapipe") is None or not MODEL.exists() or CLIP is None,
    reason="needs mediapipe, the pose_landmarker_lite model and the walking clip in var/datasets")


def video(cadence=110.0, **kwargs):
    stream = TruthStream(HDT, START, {"cadence": [(0.0, cadence), (3600.0, cadence)]})
    return phone.Video("phone-1", stream, **kwargs)


def test_features_recover_cadence_speed_and_variability():
    f = gait.features(video(step_length_m=0.6).track(0.0, seconds=20))
    assert f.cadence == pytest.approx(110, rel=0.02)
    assert f.step_length_m == pytest.approx(0.6, rel=0.02)
    assert f.gait_speed == pytest.approx(0.6 * 110 / 60, rel=0.03)
    assert f.stride_time_cv < 2 and f.step_time_symmetry == pytest.approx(1, abs=0.05)
    assert gait.metres_per_pixel(video().track(0.0)) == pytest.approx(1 / 200)
    jittered = gait.features(video(stride_jitter=0.06).track(0.0, seconds=60))
    assert 3 < jittered.stride_time_cv < 10


def test_leg_swaps_and_walking_direction_do_not_matter():
    track = video(cadence=96).track(0.0, seconds=20)
    image = track.image.copy()
    image[:, :, 0] = 640.0 - image[:, :, 0]
    swapped = np.random.default_rng(1).random(len(image)) < 0.3
    left, right = image[swapped, gait.LEFT_HEEL].copy(), image[swapped, gait.RIGHT_HEEL].copy()
    image[swapped, gait.LEFT_HEEL], image[swapped, gait.RIGHT_HEEL] = right, left
    f = gait.features(gait.PoseTrack(track.fps, image, track.world))
    assert f.cadence == pytest.approx(96, rel=0.02)
    assert f.step_length_m == pytest.approx(0.6, rel=0.03)


def test_gaps_are_filled_and_poor_tracks_refused():
    track = video().track(0.0, seconds=20)
    image = track.image.copy()
    image[::10] = np.nan
    gappy = gait.PoseTrack(track.fps, image, track.world)
    assert gait.features(gappy).cadence == pytest.approx(110, rel=0.03)
    image[: len(image) // 3] = np.nan
    with pytest.raises(gait.GaitError, match="pose is found"):
        gait.features(gait.PoseTrack(track.fps, image, track.world))
    with pytest.raises(gait.GaitError, match="steps found"):
        gait.features(video().track(0.0, seconds=1.5))


async def test_video_features_arrive_in_layer_3(tmp_path):
    backends = Backends(Settings(var_dir=tmp_path), "ahdt", ephemeral=True)
    pipeline = await build_pipeline(backends, demo_registry(), AuditLog("ahdt"))
    pipeline.subscribe()
    index = field_index()
    sim = video(cadence=104, step_length_m=0.62)
    gateway = DeviceGateway(
        backends.events, EdgeSink(pipeline),
        twin_of=lambda c: (r.twin.value if (r := index.resolve(c)) else None),
        pose_tracker=lambda body, ctype: sim.track(0.0, seconds=30),
        clock=lambda: START)
    gateway.register("phone-1", HDT, "phone")
    gateway.submit("video", b"\x00\x00\x00\x18ftypmp42", device_id="phone-1",
                   content_type="video/mp4")
    result = await gateway.flush()
    await backends.events.bus.aclose(timeout=300)
    assert result.observations == 3 and not gateway.dead_letters
    ingested = {e.payload["code"]: e.payload for e in backends.events.published
                if e.event_type == "observation.ingested"}
    assert set(ingested) >= {"gait_speed", "cadence", "stride_time_cv"}
    assert ingested["cadence"]["value"] == pytest.approx(104, rel=0.02)
    assert ingested["gait_speed"]["unit"] == "m/s"
    assert ingested["stride_time_cv"]["unit"] == "%"
    assert {e.event_type for e in backends.events.published} >= {"ingest.musculoskeletal"}
    await backends.close()


def tracked_in_child(clip: Path, out: Path) -> gait.PoseTrack:
    """Run MediaPipe in a child process.

    libmediapipe arms an exit watchdog that kills its process with SIGTRAP when interpreter
    shutdown is slow, which a long pytest session with many fixture threads can trigger.
    """
    script = (
        "import sys, numpy as np\n"
        "from pathlib import Path\n"
        "from edge.devices.decode import pose\n"
        "t = pose.track_file(Path(sys.argv[1]), Path(sys.argv[2]))\n"
        "np.savez(sys.argv[3], fps=t.fps, image=t.image, world=t.world)\n"
    )
    subprocess.run([sys.executable, "-c", script, str(clip), str(MODEL), str(out)],
                   cwd=ROOT, check=True, timeout=600)
    data = np.load(out)
    return gait.PoseTrack(float(data["fps"]), data["image"], data["world"])


@needs_pose
def test_treadmill_clip_speeds_follow_the_belt(tmp_path):
    """Yoon, Park and Damiano (2012), additional file 1: belt speeds shown on screen."""
    track = tracked_in_child(Path(CLIP), tmp_path / "track.npz")
    assert track.coverage > 0.8
    segments = [(5.0, 12.0), (13.0, 19.5), (20.5, 28.5), (29.5, 35.5), (36.5, 42.0)]
    belts = [0.5, 1.0, 1.5, 1.0, 0.5]
    speeds = [gait.features(track.window(a, b)).gait_speed for a, b in segments]
    assert speeds[0] < speeds[1] < speeds[2] > speeds[3] > speeds[4] * 0.95
    assert speeds[2] == pytest.approx(1.5, rel=0.15)
    errors = [abs(s - b) for s, b in zip(speeds, belts, strict=True)]
    assert max(errors) < 0.5
    whole = gait.features(track.window(5.0, 42.0))
    assert 70 < whole.cadence < 130
