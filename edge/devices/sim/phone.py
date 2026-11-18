"""Phone simulators: microphone clips, camera photos, walking videos, app-use logs and
self-report forms.

Cough bursts are 0.2 s noise bursts over quiet room noise, as many per clip as the truth's
`cough_events` rate gives; the clip length sets the rate's resolution (one burst per
`clip_s`). Self-report answers come from `documents["questionnaires"]`: questionnaire name ->
{linkId: answer code}.

A walking video is either a recorded clip replayed as it is or, without a pose model, the pose
track a side-view clip would give: heels swinging about the hips in antiphase at the truth's
`cadence` with `step_length_m`.
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
from PIL import Image

from edge.devices.decode.gait import (
    LANDMARKS,
    LEFT_ANKLE,
    LEFT_HEEL,
    LEFT_HIP,
    RIGHT_ANKLE,
    RIGHT_HEEL,
    RIGHT_HIP,
    PoseTrack,
)
from edge.devices.decode.media import write_wav
from edge.devices.decode.self_report import ODK_PREFIX
from edge.devices.sim.base import Simulator

QUESTIONNAIRE_BASE = "https://atra.health/fhir/Questionnaire/"
PACKAGES = ("com.whatsapp", "com.android.chrome")


@dataclass
class Microphone(Simulator):
    rate: int = 4000
    clip_s: float = 300.0

    def clip(self, t_s: float) -> bytes:
        n = int(self.rate * self.clip_s)
        audio = self.rng.normal(0, 30, n)
        coughs = round(self.stream.at("cough_events", t_s) * self.clip_s / 3600)
        burst = int(0.2 * self.rate)
        for k in range(coughs):
            start = int((k + 0.5) * n / max(coughs, 1)) - burst // 2
            audio[start:start + burst] += self.rng.normal(0, 8000, burst)
        return write_wav(audio, self.rate)


@dataclass
class Camera(Simulator):
    def photo(self) -> bytes:
        pixels = self.rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
        buf = io.BytesIO()
        Image.fromarray(pixels, "RGB").save(buf, format="PNG")
        return buf.getvalue()


@dataclass
class Video(Simulator):
    """Side view at `pixels_per_m`; the hips stay at the frame centre, as on a treadmill."""

    fps: float = 30.0
    step_length_m: float = 0.6
    stride_jitter: float = 0.0
    """SD of the stride period as a fraction of its mean."""
    leg_m: float = 0.85
    pixels_per_m: float = 200.0

    @staticmethod
    def clip(path: Path) -> bytes:
        return path.read_bytes()

    def track(self, t_s: float, seconds: float = 10.0) -> PoseTrack:
        cadence = self.stream.at("cadence", t_s)
        n = int(seconds * self.fps)
        stride = 120.0 / cadence
        periods = stride * (1 + self.stride_jitter * self.rng.standard_normal(
            int(seconds / stride) + 3))
        edges = np.concatenate([[0.0], np.cumsum(periods)])
        t = np.arange(n) / self.fps
        k = np.searchsorted(edges, t, side="right") - 1
        phase = 2 * np.pi * (k + (t - edges[k]) / periods[k])
        world = np.zeros((n, LANDMARKS, 3))
        for hip, ankle, heel, sign in ((LEFT_HIP, LEFT_ANKLE, LEFT_HEEL, 1.0),
                                       (RIGHT_HIP, RIGHT_ANKLE, RIGHT_HEEL, -1.0)):
            forward = sign * self.step_length_m / 2 * np.cos(phase)
            world[:, ankle, 0] = world[:, heel, 0] = forward
            world[:, ankle, 1] = world[:, heel, 1] = np.sqrt(self.leg_m ** 2 - forward ** 2)
            world[:, hip, 0] = 0.0
        image = 320.0 + self.pixels_per_m * world[:, :, :2]
        return PoseTrack(self.fps, image, world, self.stream.when(t_s))


@dataclass
class UsageLog(Simulator):
    """One day's `UsageStats` per truth sample, the screen time split over two apps."""

    def day(self, t_s: float) -> bytes:
        total_ms = round(self.stream.at("screen_time", t_s) * 60000)
        end = self.stream.when(t_s)
        begin = end - timedelta(days=1)
        shares = (0.6, 0.4)
        return json.dumps([{
            "packageName": p, "totalTimeInForeground": round(total_ms * s),
            "firstTimeStamp": int(begin.timestamp() * 1000),
            "lastTimeStamp": int(end.timestamp() * 1000)} for p, s in zip(
                PACKAGES, shares, strict=True)]).encode()


@dataclass
class SelfReport(Simulator):
    def questionnaire_response(self, name: str, when: datetime) -> bytes:
        answers = self.stream.documents["questionnaires"][name]
        return json.dumps({
            "resourceType": "QuestionnaireResponse", "status": "completed",
            "questionnaire": QUESTIONNAIRE_BASE + name, "authored": when.isoformat(),
            "subject": {"reference": f"Patient/{self.hdt_id}"},
            "item": [{"linkId": "items", "item": [
                {"linkId": k, "answer": [{"valueCoding": {"code": v}}]}
                for k, v in answers.items()]}]}).encode()

    def odk(self, name: str) -> bytes:
        answers = self.stream.documents["questionnaires"][name]
        fields = "".join(f"<{ODK_PREFIX}{k}>{v}</{ODK_PREFIX}{k}>" for k, v in answers.items())
        return f'<data id="{name}"><meta><instanceID>uuid:{self.device_id}</instanceID></meta>' \
               f"{fields}</data>".encode()
