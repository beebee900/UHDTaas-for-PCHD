"""Phone video → MediaPipe Pose Landmarker image and world landmarks (design 04, 4.1.1).

The model is `pose_landmarker_lite.task` (evaluation/datasets, id `mediapipe-pose-lite`), run
in VIDEO mode on one person. Frames are decoded one at a time with OpenCV and released before
the next is read, so memory does not grow with the clip length. `mediapipe` is imported only
here.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import numpy as np

from atra.config import ROOT
from edge.devices.decode.gait import LANDMARKS, Array, GaitError, PoseTrack

MODEL = ROOT / "var" / "datasets" / "mediapipe-pose-lite" / "pose_landmarker_lite.task"
SUFFIXES = {"video/mp4": ".mp4", "video/webm": ".webm", "video/ogg": ".ogv",
            "video/quicktime": ".mov"}


def track_file(path: Path, model: Path = MODEL) -> PoseTrack:
    import cv2
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision

    capture = cv2.VideoCapture(str(path))
    if not capture.isOpened():
        raise GaitError(f"cannot read video {path.name}")
    fps = float(capture.get(cv2.CAP_PROP_FPS)) or 30.0
    width = float(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    options = vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=str(model)),
        running_mode=vision.RunningMode.VIDEO, num_poses=1)
    image: list[Array] = []
    world: list[Array] = []
    no_image, no_world = np.full((LANDMARKS, 2), np.nan), np.full((LANDMARKS, 3), np.nan)
    with vision.PoseLandmarker.create_from_options(options) as landmarker:
        i = 0
        while True:
            ok, bgr = capture.read()
            if not ok:
                break
            frame = mp.Image(image_format=mp.ImageFormat.SRGB,
                             data=cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
            result = landmarker.detect_for_video(frame, round(i * 1000 / fps))
            if result.pose_world_landmarks and result.pose_landmarks:
                image.append(np.array([[p.x * width, p.y * height]
                                       for p in result.pose_landmarks[0]]))
                world.append(np.array([[p.x, p.y, p.z] for p in result.pose_world_landmarks[0]]))
            else:
                image.append(no_image)
                world.append(no_world)
            i += 1
    capture.release()
    if not image:
        return PoseTrack(fps, np.zeros((0, LANDMARKS, 2)), np.zeros((0, LANDMARKS, 3)))
    return PoseTrack(fps, np.stack(image), np.stack(world))


def track_bytes(body: bytes, content_type: str, model: Path = MODEL) -> PoseTrack:
    suffix = SUFFIXES.get(content_type.split(";")[0].strip(), ".mp4")
    with tempfile.NamedTemporaryFile(suffix=suffix) as fh:
        fh.write(body)
        fh.flush()
        return track_file(Path(fh.name), model)
