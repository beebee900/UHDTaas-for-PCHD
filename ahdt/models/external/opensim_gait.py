"""Gait biomechanics on OpenSim gait2392 (design 04, 4.5.3; design 08, WP14c step 2).

A phone-video pose track (MediaPipe world landmarks) becomes joint angles and muscle forces:

1. Virtual markers at the hip, knee, ankle, heel and toe are attached to the model at its
   joint centres. The pose landmarks are rotated into the OpenSim frame (X forward, Y up,
   Z to the right) and scaled to the model's leg length.
2. The pelvis path is rebuilt from foot contact: the lowest foot marker rests on the floor
   and the stance ankle does not move relative to the ground.
3. Inverse kinematics fits the model coordinates to the markers.
4. The ground reaction force is estimated from the model's centre of mass (no force plate):
   the total force is mass times (acceleration + gravity), shared between the feet by
   contact and by the position of the centre of mass between them, and applied at a centre
   of pressure that moves from heel to toe.
5. Static optimisation distributes the joint moments over the muscles. Reserve actuators on
   every coordinate, including the pelvis, take what the muscles cannot supply; their size
   measures how well the estimated loads fit the motion.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import butter, filtfilt, savgol_filter

from ahdt.models.arrays import Array
from ahdt.models.base import Layer4Base, ModelSpec, Params, Port
from ahdt.models.external import backends, sources
from atra import contracts as c
from atra.connectors import DTKind
from edge.devices.decode.gait import PoseTrack

GRAVITY = 9.80665
SIDES = ("r", "l")
# BlazePose indices: hip, knee, ankle, heel, foot index (left, right).
LANDMARK = {"hip": (24, 23), "knee": (26, 25), "ankle": (28, 27), "heel": (30, 29),
            "toe": (32, 31)}
RESERVE = "reserve_"
QUADRICEPS = ("rect_fem", "vas_med", "vas_int", "vas_lat")
PLANTARFLEXORS = ("soleus", "med_gas", "lat_gas")
HAMSTRINGS = ("bifemlh", "bifemsh", "semimem", "semiten")


class GaitAnalysisError(RuntimeError):
    pass


@dataclass(frozen=True)
class GaitAnalysis:
    """The result of one pose track."""

    time_s: Array
    coordinates: dict[str, Array]
    """Joint angles in degrees and pelvis translations in metres, per frame."""
    marker_rms_m: float
    marker_max_m: float
    grf_vertical_n: Array
    muscle_force_n: dict[str, Array]
    reserve_force_n: float
    runtime_s: float
    directory: Path
    scale: float
    mass_kg: float
    activations: dict[str, Array] = field(default_factory=dict)

    def peak(self, name: str) -> float:
        return float(np.max(self.coordinates[name]))

    def range(self, name: str) -> float:
        values = self.coordinates[name]
        return float(np.max(values) - np.min(values))

    def group_peak(self, prefixes: Sequence[str]) -> float:
        total = self.group_total(prefixes)
        return float(total.max()) if total.size else 0.0

    def group_total(self, prefixes: Sequence[str]) -> Array:
        rows = [v for k, v in self.muscle_force_n.items()
                if any(k.startswith(p) for p in prefixes)]
        return np.sum(rows, axis=0) if rows else np.zeros(len(self.time_s))


# Model and markers


def model_path() -> Path:
    return sources.fetch("gait2392")


def build_model(p: Params, reserves: bool = False) -> Any:
    """The gait2392 model with the virtual markers and, when asked, reserve actuators."""
    import opensim as osim

    backends.require(backends.opensim())
    model = osim.Model(str(model_path()))
    model.initSystem()
    for s in SIDES:
        for marker, joint in (("hip", f"hip_{s}"), ("knee", f"knee_{s}"),
                              ("ankle", f"ankle_{s}")):
            frame = model.getJointSet().get(joint).getChildFrame()
            model.addMarker(osim.Marker(f"{s}_{marker}", frame, osim.Vec3(0, 0, 0)))
        calcn = model.getBodySet().get(f"calcn_{s}")
        model.addMarker(osim.Marker(f"{s}_heel", calcn, osim.Vec3(0, 0, 0)))
        toes = model.getBodySet().get(f"toes_{s}")
        model.addMarker(osim.Marker(f"{s}_toe", toes, osim.Vec3(p["toe_tip_ahead_m"], 0, 0)))
    if reserves:
        coords = model.getCoordinateSet()
        for i in range(coords.getSize()):
            coord = coords.get(i)
            actuator = osim.CoordinateActuator(coord.getName())
            actuator.setName(RESERVE + coord.getName())
            actuator.setOptimalForce(1.0)
            model.addForce(actuator)
    model.finalizeConnections()
    return model


def neutral_markers(model: Any) -> dict[str, Array]:
    state = model.initSystem()
    markers = model.getMarkerSet()
    out = {}
    for i in range(markers.getSize()):
        m = markers.get(i)
        v = m.getLocationInGround(state)
        out[m.getName()] = np.array([v.get(0), v.get(1), v.get(2)])
    return out


# Landmarks to markers


def _fill(x: Array) -> Array:
    ok = np.isfinite(x)
    idx = np.arange(len(x))
    out: Array = np.interp(idx, idx[ok], x[ok])
    return out


def _smooth(x: Array, fps: float, cutoff_hz: float) -> Array:
    if fps <= 2 * cutoff_hz or len(x) <= 27:
        return x
    b, a = butter(4, cutoff_hz / (fps / 2))
    out: Array = filtfilt(b, a, x, axis=0)
    return out


@dataclass(frozen=True)
class MarkerTrack:
    time_s: Array
    ground: dict[str, Array]
    """Marker positions in the OpenSim ground frame, shape (frames, 3) each."""
    scale: float
    direction: int


def markers_from_track(track: PoseTrack, neutral: Mapping[str, Array], p: Params,
                       start_s: float = 0.0, seconds: float | None = None) -> MarkerTrack:
    """Rotate, scale and place the world landmarks as ground-frame marker paths.

    The lateral coordinate of every marker is the model's neutral one: a phone filmed from
    the side measures depth poorly.
    """
    seconds = p["analysis_seconds"] if seconds is None else seconds
    window = track.window(start_s, start_s + seconds)
    if window.frames < 8:
        raise GaitAnalysisError("the pose track is shorter than eight frames")
    world = window.world
    needed = [i for kind in LANDMARK.values() for i in kind]
    coverage = float(np.mean(np.all(np.isfinite(world[:, needed, 0]), axis=1)))
    if coverage < p["min_coverage"]:
        raise GaitAnalysisError(f"only {coverage:.0%} of the frames show the legs")
    fps = window.fps
    rel: dict[str, Array] = {}
    for kind, (right, left) in LANDMARK.items():
        for s, idx in (("r", right), ("l", left)):
            xyz = np.stack([_fill(world[:, idx, k]) for k in range(3)], axis=1)
            rel[f"{s}_{kind}"] = _smooth(xyz, fps, p["marker_cutoff_hz"])
    ahead = np.mean([rel[f"{s}_toe"][:, 0] - rel[f"{s}_heel"][:, 0] for s in SIDES])
    direction = 1 if ahead >= 0 else -1
    local = {k: np.stack([direction * v[:, 0], -v[:, 1]], axis=1) for k, v in rel.items()}
    # Leg length, hip to ankle through the knee, of the person and of the model.
    def leg(points: Mapping[str, Array], s: str) -> float:
        return float(np.median(
            np.linalg.norm(points[f"{s}_hip"][:, :2] - points[f"{s}_knee"][:, :2], axis=1)
            + np.linalg.norm(points[f"{s}_knee"][:, :2] - points[f"{s}_ankle"][:, :2],
                             axis=1)))

    person = float(np.mean([leg(local, s) for s in SIDES]))
    flat = {k: v[None, :2] for k, v in neutral.items()}
    model_leg = float(np.mean([leg(flat, s) for s in SIDES]))
    if person <= 0:
        raise GaitAnalysisError("the leg length of the pose track is zero")
    scale = model_leg / person
    local = {k: v * scale for k, v in local.items()}
    hip_mid = np.array([neutral["r_hip"][0] + neutral["l_hip"][0],
                        neutral["r_hip"][1] + neutral["l_hip"][1]]) / 2
    heights = {k: neutral[k][1] for k in neutral}
    n = window.frames
    hip_y = np.max([heights[f"{s}_{kind}"] - local[f"{s}_{kind}"][:, 1]
                    for s in SIDES for kind in ("heel", "toe")], axis=0)
    # The stance foot is the one whose lowest marker is lower.
    low = {s: np.min([local[f"{s}_{kind}"][:, 1] - heights[f"{s}_{kind}"]
                      for kind in ("heel", "toe")], axis=0) for s in SIDES}
    stance_right = low["r"] <= low["l"]
    ankle_dx = np.diff(local["r_ankle"][:, 0], prepend=local["r_ankle"][0, 0])
    ankle_dx = np.where(stance_right, ankle_dx, np.diff(local["l_ankle"][:, 0],
                                                        prepend=local["l_ankle"][0, 0]))
    hip_x = hip_mid[0] - np.cumsum(ankle_dx)
    hip_x[0] = hip_mid[0]
    hip_x = _smooth(hip_x, fps, p["marker_cutoff_hz"])
    ground: dict[str, Array] = {}
    for key, xy in local.items():
        ground[key] = np.stack([xy[:, 0] + hip_x, xy[:, 1] + hip_y,
                                np.full(n, neutral[key][2])], axis=1)
    return MarkerTrack(np.arange(n) / fps, ground, scale, direction)


# Pose tracks from the model


def model_gait_angles(phase: float, side: int) -> dict[str, float]:
    """Hip, knee and ankle angles in degrees of a walking pattern; `side` 0 or 1 is the leg."""
    leg = phase + math.pi * side
    return {"hip_flexion": 5.0 + 25.0 * math.sin(leg),
            "knee_angle": -25.0 * (1.0 + math.sin(leg - 0.5)),
            "ankle_angle": 8.0 * math.sin(leg + 1.0)}


def model_track(p: Params, seconds: float = 3.3, fps: float = 30.0, period_s: float = 1.1
                ) -> tuple[PoseTrack, dict[str, float]]:
    """A pose track made from the model's own markers while its legs follow a walking pattern.

    It has the structure of a MediaPipe world track (X forward, Y down, origin at the hip
    centre) and known joint angles. Returns the track and the peak knee flexion that made it.
    """
    model = build_model(p)
    state = model.initSystem()
    coords = model.getCoordinateSet()
    frames = int(seconds * fps)
    world = np.full((frames, 33, 3), np.nan)
    knee_peak = 0.0
    for k in range(frames):
        phase = 2.0 * math.pi * k / (fps * period_s)
        for side, s in enumerate(SIDES):
            for joint, value in model_gait_angles(phase, side).items():
                coords.get(f"{joint}_{s}").setValue(state, math.radians(value), False)
                if joint == "knee_angle":
                    knee_peak = max(knee_peak, -value)
        model.realizePosition(state)
        found = {}
        for i in range(model.getMarkerSet().getSize()):
            marker = model.getMarkerSet().get(i)
            v = marker.getLocationInGround(state)
            found[marker.getName()] = np.array([v.get(0), v.get(1), v.get(2)])
        centre = (found["r_hip"] + found["l_hip"]) / 2.0
        for kind, (right, left) in LANDMARK.items():
            for s, idx in (("r", right), ("l", left)):
                rel = found[f"{s}_{kind}"] - centre
                world[k, idx] = [rel[0], -rel[1], rel[2]]
    image = np.zeros((frames, 33, 2))
    return PoseTrack(fps, image, world), {"knee_flexion_peak": knee_peak}


# Inverse kinematics


def _write_trc(path: Path, t: Array, markers: Mapping[str, Array]) -> None:
    names = list(markers)
    fps = 1.0 / float(t[1] - t[0])
    head = ["PathFileType\t4\t(X/Y/Z)\t" + path.name,
            "DataRate\tCameraRate\tNumFrames\tNumMarkers\tUnits\tOrigDataRate\t"
            "OrigDataStartFrame\tOrigNumFrames",
            f"{fps:g}\t{fps:g}\t{len(t)}\t{len(names)}\tm\t{fps:g}\t1\t{len(t)}",
            "Frame#\tTime\t" + "\t\t\t".join(names) + "\t\t",
            "\t\t" + "\t".join(f"X{i + 1}\tY{i + 1}\tZ{i + 1}" for i in range(len(names)))]
    rows = []
    for k in range(len(t)):
        cells = "\t".join(f"{markers[n][k, j]:.6f}" for n in names for j in range(3))
        rows.append(f"{k + 1}\t{t[k]:.6f}\t{cells}")
    path.write_text("\n".join(head + rows) + "\n", encoding="ascii")


def read_storage(path: Path) -> tuple[Array, dict[str, Array]]:
    """Time and the columns of an OpenSim .mot or .sto file."""
    lines = path.read_text(encoding="ascii").splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.strip().lower() == "endheader")
    names = lines[start + 1].split()
    data = np.array([[float(x) for x in ln.split()] for ln in lines[start + 2:] if ln.strip()])
    return data[:, 0], {n: data[:, i] for i, n in enumerate(names) if i > 0}


def write_storage(path: Path, name: str, t: Array, columns: Mapping[str, Array],
                  in_degrees: bool = False) -> None:
    header = [name, "version=1", f"nRows={len(t)}", f"nColumns={len(columns) + 1}",
              f"inDegrees={'yes' if in_degrees else 'no'}", "endheader",
              "time\t" + "\t".join(columns)]
    rows = [f"{t[k]:.6f}\t" + "\t".join(f"{v[k]:.8g}" for v in columns.values())
            for k in range(len(t))]
    path.write_text("\n".join(header + rows) + "\n", encoding="ascii")


def inverse_kinematics(model: Any, markers: MarkerTrack, directory: Path, p: Params
                       ) -> tuple[Path, float, float]:
    import opensim as osim

    trc = directory / "markers.trc"
    _write_trc(trc, markers.time_s, markers.ground)
    tool = osim.InverseKinematicsTool()
    tool.setModel(model)
    tool.setMarkerDataFileName(str(trc))
    tool.setStartTime(float(markers.time_s[0]))
    tool.setEndTime(float(markers.time_s[-1]))
    tool.setResultsDir(str(directory))
    mot = directory / "ik.mot"
    tool.setOutputMotionFileName(str(mot))
    tasks = tool.getIKTaskSet()
    weights = {"hip": p["weight_hip"], "knee": p["weight_knee"], "ankle": p["weight_ankle"],
               "heel": p["weight_foot"], "toe": p["weight_foot"]}
    for name in markers.ground:
        task = osim.IKMarkerTask()
        task.setName(name)
        task.setApply(True)
        task.setWeight(weights[name.split("_", 1)[1]])
        tasks.cloneAndAppend(task)
    if not tool.run() or not mot.exists():
        raise GaitAnalysisError("inverse kinematics did not produce a motion file")
    rms, worst = marker_errors(model, mot, markers)
    return mot, rms, worst


def _set_pose(model: Any, state: Any, names: Sequence[str], values: Sequence[float]) -> None:
    import opensim as osim

    coords = model.getCoordinateSet()
    for name, value in zip(names, values, strict=True):
        coord = coords.get(name)
        rotational = coord.getMotionType() == osim.Coordinate.Rotational
        coord.setValue(state, math.radians(value) if rotational else value, False)


def _walk(model: Any, mot: Path, per_frame: Any) -> list[Any]:
    t, columns = read_storage(mot)
    names = [n for n in columns if model.getCoordinateSet().contains(n)]
    state = model.initSystem()
    rows = []
    for k in range(len(t)):
        _set_pose(model, state, names, [columns[n][k] for n in names])
        model.realizePosition(state)
        rows.append(per_frame(state))
    return rows


def marker_errors(model: Any, mot: Path, markers: MarkerTrack) -> tuple[float, float]:
    names = list(markers.ground)
    positions = _walk(model, mot, lambda s: {
        n: np.array([(v := model.getMarkerSet().get(n).getLocationInGround(s)).get(0),
                     v.get(1), v.get(2)]) for n in names})
    errors = np.array([[np.linalg.norm(row[n] - markers.ground[n][k]) for n in names]
                       for k, row in enumerate(positions)])
    return float(np.sqrt(np.mean(errors ** 2))), float(errors.max())


# Ground reaction force


def estimate_grf(model: Any, mot: Path, markers: MarkerTrack, p: Params
                 ) -> tuple[Array, dict[str, Array], float]:
    """Estimated ground reaction forces, as the columns of an OpenSim force file.

    Returns time, the columns and the body mass. The estimate has no force plate behind it:
    see the module description.
    """
    t, _ = read_storage(mot)
    mass = float(model.getTotalMass(model.initSystem()))
    names = [f"{s}_{k}" for s in SIDES for k in ("heel", "toe")]

    def sample(state: Any) -> dict[str, Any]:
        com = model.calcMassCenterPosition(state)
        out: dict[str, Any] = {"com": np.array([com.get(0), com.get(1), com.get(2)])}
        for n in names:
            v = model.getMarkerSet().get(n).getLocationInGround(state)
            out[n] = np.array([v.get(0), v.get(1), v.get(2)])
        return out

    rows = _walk(model, mot, sample)
    com = np.array([r["com"] for r in rows])
    fps = 1.0 / float(t[1] - t[0])
    window = min(len(t) if len(t) % 2 else len(t) - 1, int(p["com_window_s"] * fps) | 1)
    acc = np.stack([savgol_filter(com[:, j], max(window, 5), 3, deriv=2, delta=1 / fps)
                    for j in range(3)], axis=1)
    total = mass * (acc + np.array([0.0, GRAVITY, 0.0]))
    floor = {n: neutral_markers(model)[n][1] for n in names}
    height = {n: np.array([r[n][1] for r in rows]) - floor[n] for n in names}
    soft = p["contact_softness_m"]
    contact = {s: np.maximum(0.0, 1.0 - np.minimum(height[f"{s}_heel"],
                                                    height[f"{s}_toe"]) / soft)
               for s in SIDES}
    share = _share(contact, com, rows)
    columns: dict[str, Array] = {}
    for s in SIDES:
        force = total * share[s][:, None]
        weight = {k: np.maximum(0.0, 1.0 - height[f"{s}_{k}"] / soft) for k in ("heel", "toe")}
        denom = weight["heel"] + weight["toe"]
        mid = np.array([(r[f"{s}_heel"] + r[f"{s}_toe"]) / 2 for r in rows])
        heel = np.array([r[f"{s}_heel"] for r in rows])
        toe = np.array([r[f"{s}_toe"] for r in rows])
        safe = np.where(denom > 1e-9, denom, 1.0)[:, None]
        cop = np.where(denom[:, None] > 1e-9,
                       (weight["heel"][:, None] * heel + weight["toe"][:, None] * toe) / safe,
                       mid)
        cop[:, 1] = 0.0
        for j, axis in enumerate("xyz"):
            columns[f"{s}_ground_force_v{axis}"] = force[:, j]
        for j, axis in enumerate("xyz"):
            columns[f"{s}_ground_force_p{axis}"] = cop[:, j]
        for axis in "xyz":
            columns[f"{s}_ground_torque_{axis}"] = np.zeros(len(t))
    return t, columns, mass


def _share(contact: Mapping[str, Array], com: Array, rows: Sequence[Mapping[str, Any]]
           ) -> dict[str, Array]:
    """Fraction of the total force carried by each foot at each frame."""
    cr, cl = contact["r"], contact["l"]
    xr = np.array([(r["r_heel"][0] + r["r_toe"][0]) / 2 for r in rows])
    xl = np.array([(r["l_heel"][0] + r["l_toe"][0]) / 2 for r in rows])
    span = xr - xl
    between = np.where(np.abs(span) > 1e-3, (com[:, 0] - xl) / np.where(
        np.abs(span) > 1e-3, span, 1.0), 0.5)
    right = np.clip(between, 0.0, 1.0)
    both = (cr > 0) & (cl > 0)
    share_r = np.where(both, right, np.where(cr > 0, 1.0, np.where(cl > 0, 0.0, 0.5)))
    neither = (cr <= 0) & (cl <= 0)
    share_r = np.where(neither, 0.0, share_r)
    share_l = np.where(neither, 0.0, 1.0 - share_r)
    return {"r": share_r, "l": share_l}


def _external_loads_xml(grf: Path) -> str:
    forces = "".join(
        f'<ExternalForce name="{s}_grf"><applied_to_body>calcn_{s}</applied_to_body>'
        f"<force_expressed_in_body>ground</force_expressed_in_body>"
        f"<point_expressed_in_body>ground</point_expressed_in_body>"
        f"<force_identifier>{s}_ground_force_v</force_identifier>"
        f"<point_identifier>{s}_ground_force_p</point_identifier>"
        f"<torque_identifier>{s}_ground_torque_</torque_identifier></ExternalForce>"
        for s in SIDES)
    return ('<?xml version="1.0" encoding="UTF-8" ?><OpenSimDocument Version="40000">'
            f'<ExternalLoads name="grf"><objects>{forces}</objects><groups/>'
            f"<datafile>{grf.name}</datafile></ExternalLoads></OpenSimDocument>\n")


# Static optimisation


def static_optimisation(model: Any, mot: Path, grf: Path, directory: Path, p: Params,
                        t0: float, t1: float) -> tuple[Array, dict[str, Array],
                                                       dict[str, Array]]:
    import opensim as osim

    loads = directory / "grf_loads.xml"
    loads.write_text(_external_loads_xml(grf), encoding="ascii")
    so = osim.StaticOptimization()
    so.setName("so")
    so.setStartTime(t0)
    so.setEndTime(t1)
    so.setUseModelForceSet(True)
    so.setActivationExponent(2.0)
    so.setUseMusclePhysiology(False)
    so.setConvergenceCriterion(1e-4)
    so.setMaxIterations(int(p["so_max_iterations"]))
    model_file = directory / "gait_reserves.osim"
    model.printToXML(str(model_file))
    tool = osim.AnalyzeTool()
    tool.setName("so")
    tool.setModelFilename(str(model_file))
    tool.updAnalysisSet().cloneAndAppend(so)
    tool.setCoordinatesFileName(str(mot))
    tool.setExternalLoadsFileName(str(loads))
    tool.setLowpassCutoffFrequency(p["coordinate_cutoff_hz"])
    tool.setInitialTime(t0)
    tool.setFinalTime(t1)
    tool.setResultsDir(str(directory))
    setup = directory / "so_setup.xml"
    tool.printToXML(str(setup))
    if not osim.AnalyzeTool(str(setup)).run():
        raise GaitAnalysisError("static optimisation failed")
    force_file = directory / "so_so_force.sto"
    act_file = directory / "so_so_activation.sto"
    if not (force_file.exists() and act_file.exists()):
        raise GaitAnalysisError("static optimisation wrote no results")
    t, forces = read_storage(force_file)
    _, activations = read_storage(act_file)
    return t, forces, activations


def _sample_motion(mot: Path, out: Path, p: Params) -> tuple[float, float]:
    """Write the first `so_window_s` seconds of the motion at `so_rate_hz`; return its span."""
    t, columns = read_storage(mot)
    step = max(1, round(1.0 / (float(t[1] - t[0]) * p["so_rate_hz"])))
    keep = np.nonzero(t <= t[0] + p["so_window_s"])[0][::step]
    write_storage(out, "ik_so", t[keep], {k: v[keep] for k, v in columns.items()},
                  in_degrees=True)
    return float(t[keep][0]), float(t[keep][-1])


# Analysis


def analyse(track: PoseTrack, p: Params, directory: Path, *, start_s: float = 0.0,
            seconds: float | None = None, muscles: bool = True) -> GaitAnalysis:
    """Inverse kinematics and, with `muscles`, static optimisation of one pose track."""
    started = time.monotonic()
    directory.mkdir(parents=True, exist_ok=True)
    model = build_model(p)
    neutral = neutral_markers(model)
    markers = markers_from_track(track, neutral, p, start_s, seconds)
    mot, rms, worst = inverse_kinematics(model, markers, directory, p)
    t, columns = read_storage(mot)
    coordinates = {k: v for k, v in columns.items() if model.getCoordinateSet().contains(k)}
    mass = float(model.getTotalMass(model.initSystem()))
    grf_v: Array = np.zeros(len(t))
    muscle: dict[str, Array] = {}
    activation: dict[str, Array] = {}
    reserve = 0.0
    if muscles:
        gt, gcols, mass = estimate_grf(model, mot, markers, p)
        grf = directory / "grf.mot"
        write_storage(grf, "grf", gt, gcols)
        grf_v = gcols["r_ground_force_vy"] + gcols["l_ground_force_vy"]
        so_model = build_model(p, reserves=True)
        sampled = directory / "ik_so.mot"
        so_t0, so_t1 = _sample_motion(mot, sampled, p)
        _, forces, activation = static_optimisation(so_model, sampled, grf, directory, p,
                                                     so_t0, so_t1)
        muscle = {k: v for k, v in forces.items() if not k.startswith(RESERVE)}
        pelvis = [v for k, v in forces.items() if k.startswith(RESERVE + "pelvis_")]
        reserve = float(max((np.abs(v).max() for v in pelvis), default=0.0))
    return GaitAnalysis(time_s=t, coordinates=coordinates, marker_rms_m=rms,
                        marker_max_m=worst, grf_vertical_n=grf_v, muscle_force_n=muscle,
                        reserve_force_n=reserve, runtime_s=time.monotonic() - started,
                        directory=directory, scale=markers.scale, mass_kg=mass,
                        activations=activation)


def model_check(p: Params, *, muscles: bool) -> dict[str, float]:
    """Analyse a pose track made by the model itself and compare with what made it."""
    period_s = 1.1
    track, truth = model_track(p, seconds=3 * period_s, period_s=period_s)
    work = sources.directory().parent / "jobs" / "opensim" / (
        "check-muscles" if muscles else "check-kinematics")
    a = analyse(track, p, work, seconds=3 * period_s, muscles=muscles)
    out = {"marker_rms_m": a.marker_rms_m,
           "knee_peak_error_deg": abs(_knee_peak(a) - truth["knee_flexion_peak"])}
    if muscles:
        out["grf_weight_error"] = abs(float(np.mean(a.grf_vertical_n))
                                      - a.mass_kg * GRAVITY) / (a.mass_kg * GRAVITY)
    return out


class OpenSimGaitModel(Layer4Base):
    """Shared behaviour of the two gait2392 models; subclasses choose their outputs."""

    def initial_state(self, p: Params, inputs: Mapping[str, Any]) -> dict[str, Any]:
        return {port.name: 0.0 for port in self.spec.outputs}

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Mapping[str, Any]
                 ) -> dict[str, Any]:
        base = self.initial_state(p, inputs)
        base.update({k: float(v) for k, v in state.items() if k in base})
        track = inputs.get("pose_track")
        if track is None:
            return base
        analysis = analyse(track, p, self.work_dir(inputs), muscles=self.uses_muscles)
        base.update(self.summarise(analysis))
        return base

    uses_muscles = False

    def work_dir(self, inputs: Mapping[str, Any]) -> Path:
        stamp = inputs.get("job_id") or f"job-{int(time.time() * 1000)}"
        return sources.directory().parent / "jobs" / "opensim" / str(stamp)

    def summarise(self, a: GaitAnalysis) -> dict[str, float]:
        raise NotImplementedError

    async def predict(self, inputs: Mapping[str, Any], state: c.InstanceRecord | None
                      ) -> c.ModelOutput:
        p = self.parameters(state)
        current = dict(state.state) if state is not None else self.initial_state(p, inputs)
        values = await asyncio.to_thread(self.evaluate, p, current, inputs)
        recorded = {k: v for k, v in inputs.items() if k != "pose_track"}
        track = inputs.get("pose_track")
        if track is not None:
            recorded["pose_track_sha256"] = hashlib.sha256(track.world.tobytes()).hexdigest()
        return self._output(state, recorded, values)


class SkeletalMuscleModel(OpenSimGaitModel):
    spec = ModelSpec(
        model_id="ahdt.musculoskeletal.skeletal_muscle_and_biomechanics",
        twin=DTKind.MUSCULOSKELETAL, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Joint angles and muscle forces of walking from a phone-video pose track",
        inputs=(Port("pose_track", "1", "input:scenario"),),
        outputs=(Port("knee_flexion_peak", "deg"), Port("hip_flexion_range", "deg"),
                 Port("ankle_angle_range", "deg"), Port("quadriceps_peak_force", "N"),
                 Port("plantarflexor_peak_force", "N"), Port("hamstring_peak_force", "N"),
                 Port("marker_rms_error", "m"), Port("reserve_force_peak", "N")),
        explainers=("sensitivity.local",),
        fidelity_note="OpenSim gait2392. The ground reaction force is an assumption: it is "
                      "estimated from the centre of mass and the foot contact, not measured. "
                      "Static optimisation covers one stride sampled at 15 Hz and ignores the "
                      "force-length-velocity dependence of muscle. The reserve force peak "
                      "shows how much load the muscles could not carry.")
    params_stem = "opensim"
    uses_muscles = True

    def summarise(self, a: GaitAnalysis) -> dict[str, float]:
        hip = max(a.range("hip_flexion_r"), a.range("hip_flexion_l"))
        ankle = max(a.range("ankle_angle_r"), a.range("ankle_angle_l"))
        sides = ("_r", "_l")

        def group(prefixes: Sequence[str]) -> float:
            return max(a.group_peak([p + s for p in prefixes]) for s in sides)

        return {"knee_flexion_peak": _knee_peak(a),
                "hip_flexion_range": hip, "ankle_angle_range": ankle,
                "quadriceps_peak_force": group(QUADRICEPS),
                "plantarflexor_peak_force": group(PLANTARFLEXORS),
                "hamstring_peak_force": group(HAMSTRINGS),
                "marker_rms_error": a.marker_rms_m, "reserve_force_peak": a.reserve_force_n}


def _knee_peak(a: GaitAnalysis) -> float:
    """Peak knee flexion; the gait2392 knee angle is negative in flexion."""
    return float(max(-a.coordinates["knee_angle_r"].min(),
                     -a.coordinates["knee_angle_l"].min()))


class BiomechanicalKinematicModel(OpenSimGaitModel):
    spec = ModelSpec(
        model_id="ahdt.whole_body.biomechanical_and_kinematic",
        twin=DTKind.WHOLE_BODY, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Whole-body joint kinematics of walking from a phone-video pose track",
        inputs=(Port("pose_track", "1", "input:scenario"),),
        outputs=(Port("hip_flexion_range", "deg"), Port("knee_flexion_peak", "deg"),
                 Port("ankle_angle_range", "deg"), Port("pelvis_vertical_range", "m"),
                 Port("marker_rms_error", "m")),
        explainers=("sensitivity.local",),
        fidelity_note="OpenSim gait2392 inverse kinematics of virtual hip, knee, ankle, heel "
                      "and toe markers; the lateral coordinate is the model's, so frontal-plane "
                      "motion is not measured.")
    params_stem = "opensim_kinematics"

    def summarise(self, a: GaitAnalysis) -> dict[str, float]:
        return {"hip_flexion_range": max(a.range("hip_flexion_r"), a.range("hip_flexion_l")),
                "knee_flexion_peak": _knee_peak(a),
                "ankle_angle_range": max(a.range("ankle_angle_r"), a.range("ankle_angle_l")),
                "pelvis_vertical_range": a.range("pelvis_ty"),
                "marker_rms_error": a.marker_rms_m}
