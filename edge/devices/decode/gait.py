"""Gait features from a pose landmark track of a phone video (design 04, 4.1.1).

The phone films the walker from the side. The track holds, per frame, the 33 BlazePose
landmarks in image pixels and as world landmarks in metres (MediaPipe Pose Landmarker); a
frame without a detected pose is NaN.

Steps are the maxima of the horizontal distance between the two heels in the image, which
peaks at every heel strike (the double-support instant). The distance does not need to know
which foot is which, so it is not affected when the model swaps the near and far leg. The
heel distance is gap-filled linearly and low-pass filtered (zero-lag Butterworth,
`CUTOFF_HZ`) before peak detection. Pixels become metres through the hip-to-ankle length:
its median in world landmarks over its median in the image.

| Field | Unit | Definition |
|---|---|---|
| `cadence` | /min | steps per minute, 60 / mean step time |
| `gait_speed` | m/s | mean step length / mean step time |
| `stride_time_cv` | % | SD / mean of the stride times (every second step) |

On a treadmill the step length equals the overground step length at the belt speed, so
`gait_speed` estimates the belt speed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
import numpy.typing as npt
from scipy.signal import butter, filtfilt, find_peaks

from edge.devices.decode.observations import CodedReading, field_reading

LEFT_HIP, RIGHT_HIP = 23, 24
LEFT_ANKLE, RIGHT_ANKLE = 27, 28
LEFT_HEEL, RIGHT_HEEL = 29, 30
LANDMARKS = 33
CUTOFF_HZ = 6.0
MIN_COVERAGE = 0.8
MIN_STEP_S = 0.25
MIN_PROMINENCE = 0.3
MIN_STEPS = 4

type Array = npt.NDArray[np.float64]


class GaitError(ValueError):
    pass


@dataclass(frozen=True)
class PoseTrack:
    fps: float
    image: Array
    """Shape (frames, 33, 2): x and y in pixels."""
    world: Array
    """Shape (frames, 33, 3): metres, origin at the hip centre."""
    t0: datetime | None = None

    def __post_init__(self) -> None:
        if self.image.ndim != 3 or self.image.shape[1:] != (LANDMARKS, 2):
            raise GaitError("image landmarks are 33 (x, y) pairs per frame")
        if self.world.shape != (self.image.shape[0], LANDMARKS, 3):
            raise GaitError("world landmarks are 33 (x, y, z) points per image frame")
        if self.fps <= 0:
            raise GaitError("the frame rate is positive")

    @property
    def frames(self) -> int:
        return int(self.image.shape[0])

    @property
    def coverage(self) -> float:
        if not self.frames:
            return 0.0
        return float(np.mean(np.isfinite(self.image[:, LEFT_HEEL, 0])))

    def window(self, start_s: float, end_s: float) -> PoseTrack:
        a, b = round(start_s * self.fps), round(end_s * self.fps)
        t0 = None if self.t0 is None else self.t0 + timedelta(seconds=a / self.fps)
        return PoseTrack(self.fps, self.image[a:b], self.world[a:b], t0)


@dataclass(frozen=True)
class GaitFeatures:
    cadence: float
    gait_speed: float
    stride_time_cv: float
    steps: int
    step_time_s: float
    step_length_m: float
    step_time_symmetry: float
    """Mean of odd step times / mean of even step times; 1 is symmetric."""

    def readings(self, time: datetime | None = None) -> list[CodedReading]:
        return [*field_reading("gait_speed", self.gait_speed, "m/s", time),
                *field_reading("cadence", self.cadence, "/min", time),
                *field_reading("stride_time_cv", self.stride_time_cv, "%", time)]


def _filled(x: Array) -> Array:
    ok = np.isfinite(x)
    idx = np.arange(len(x))
    out: Array = np.interp(idx, idx[ok], x[ok])
    return out


def _lowpass(x: Array, fps: float) -> Array:
    if fps <= 2 * CUTOFF_HZ or len(x) <= 27:
        return x
    b, a = butter(4, CUTOFF_HZ / (fps / 2))
    out: Array = filtfilt(b, a, x)
    return out


def metres_per_pixel(track: PoseTrack) -> float:
    def leg(points: Array) -> float:
        lengths = [np.linalg.norm(points[:, hip] - points[:, ankle], axis=1)
                   for hip, ankle in ((LEFT_HIP, LEFT_ANKLE), (RIGHT_HIP, RIGHT_ANKLE))]
        return float(np.nanmedian(np.concatenate(lengths)))

    image = leg(track.image)
    if not np.isfinite(image) or image <= 0:
        raise GaitError("no leg length in the image")
    return leg(track.world) / image


def heel_distance(track: PoseTrack) -> Array:
    """Horizontal distance between the heels in pixels, filtered."""
    d = np.abs(track.image[:, LEFT_HEEL, 0] - track.image[:, RIGHT_HEEL, 0])
    return _lowpass(_filled(d), track.fps)


def heel_strikes(distance: Array, fps: float) -> npt.NDArray[np.int64]:
    span = float(np.percentile(distance, 95) - np.percentile(distance, 5))
    peaks, _ = find_peaks(distance, distance=max(1, int(MIN_STEP_S * fps)),
                          prominence=MIN_PROMINENCE * span)
    out: npt.NDArray[np.int64] = np.asarray(peaks, dtype=np.int64)
    return out


def features(track: PoseTrack) -> GaitFeatures:
    if track.coverage < MIN_COVERAGE:
        raise GaitError(f"a pose is found in {track.coverage:.0%} of frames, "
                        f"below {MIN_COVERAGE:.0%}")
    distance = heel_distance(track)
    strikes = heel_strikes(distance, track.fps)
    if len(strikes) < MIN_STEPS + 1:
        raise GaitError(f"{max(len(strikes) - 1, 0)} steps found, {MIN_STEPS} needed")
    steps = np.diff(strikes) / track.fps
    strides = (strikes[2:] - strikes[:-2]) / track.fps
    step_time = float(np.mean(steps))
    step_length = float(np.mean(distance[strikes])) * metres_per_pixel(track)
    return GaitFeatures(
        cadence=60.0 / step_time,
        gait_speed=step_length / step_time,
        stride_time_cv=float(100 * np.std(strides) / np.mean(strides)),
        steps=len(steps),
        step_time_s=step_time,
        step_length_m=step_length,
        step_time_symmetry=float(np.mean(steps[0::2]) / np.mean(steps[1::2])),
    )
