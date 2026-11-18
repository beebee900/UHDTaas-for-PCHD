"""openCARP tissue simulation as a batch job (design 04, 4.5.3; design 08, WP14c step 1).

The job turns a scenario into an openCARP parameter file, meshes a tissue slab, runs the
simulator, and reads the activation map and the action potential duration from the
transmembrane voltage. Results are written next to a mesh file that VTK.js loads.
Drug block scenarios scale the IKr conductance of the ten Tusscher-Panfilov model.
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import tempfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.base import Layer4Base, ModelSpec, Params, Port
from ahdt.models.external import backends, baselines, sources
from atra import contracts as c
from atra.connectors import DTKind

IONIC_MODEL = "tenTusscherPanfilov"
IGB_HEADER = 1024
RUN_TIMEOUT_S = 600


@dataclass(frozen=True)
class TissueScenario:
    heart_rate: float = 60.0
    ikr_block: float = 0.0
    """Fraction of the IKr conductance blocked, from 0 to 1."""
    conductance_scale: Mapping[str, float] | None = None
    """Other ionic conductance factors by model parameter name, for example GKs."""

    def im_param(self) -> str:
        scales = {"GKr": 1.0 - self.ikr_block, **(self.conductance_scale or {})}
        return ",".join(f"{k}*{v:g}" for k, v in scales.items() if v != 1.0)


@dataclass(frozen=True)
class TissueResult:
    apd90_ms: float
    qt_surrogate_ms: float
    conduction_velocity_m_s: float
    activated_fraction: float
    apd90_dispersion_ms: float
    runtime_s: float
    directory: Path
    mesh_json: Path
    mesh_vtk: Path


def _env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["LD_LIBRARY_PATH"] = f"{root / 'usr' / 'lib'}:{env.get('LD_LIBRARY_PATH', '')}"
    return env


def _write_mesh(root: Path, p: Params, directory: Path) -> Path:
    """Mesh the slab in `directory`; openCARP reads paths with spaces wrongly, so the
    parameter file names the mesh and output relative to the working directory."""
    base = Path("slab")
    subprocess.run(
        [str(root / "usr" / "bin" / "mesher"), "-size[0]", f"{p['slab_length_cm']}",
         "-size[1]", f"{p['slab_width_cm']}", "-size[2]", "0.0",
         "-resolution[0]", f"{p['resolution_um']}", "-resolution[1]", f"{p['resolution_um']}",
         "-resolution[2]", f"{p['resolution_um']}", "-mesh", str(base)],
        check=True, capture_output=True, env=_env(root), timeout=120,
        cwd=directory)
    return directory / base


def parameter_file(p: Params, scenario: TissueScenario, mesh: Path, sim_id: str) -> str:
    bcl = 60000.0 / scenario.heart_rate
    beats = int(p["beats"])
    half_x = p["slab_length_cm"] * 5000.0
    half_y = p["slab_width_cm"] * 5000.0
    lines = [
        f"meshname = {mesh}", f"simID = {sim_id}", f"tend = {bcl * (beats - 1) + 600:g}",
        f"dt = {p['dt_us']:g}", "spacedt = 2", "timedt = 200", "bidomain = 0",
        "num_imp_regions = 1", f"imp_region[0].im = {IONIC_MODEL}",
        "imp_region[0].num_IDs = 1", "imp_region[0].ID[0] = 1"]
    if scenario.im_param():
        lines.append(f"imp_region[0].im_param = {scenario.im_param()}")
    lines += [
        "num_gregions = 1", "gregion[0].num_IDs = 1", "gregion[0].ID[0] = 1",
        f"gregion[0].g_il = {p['g_il']:g}", f"gregion[0].g_it = {p['g_it']:g}",
        f"gregion[0].g_in = {p['g_it']:g}", f"gregion[0].g_el = {p['g_el']:g}",
        f"gregion[0].g_et = {p['g_et']:g}", f"gregion[0].g_en = {p['g_et']:g}",
        "num_stim = 1", "stim[0].crct.type = 0", "stim[0].elec.geom_type = 2",
        f"stim[0].elec.p0[0] = {-half_x - 400:g}", f"stim[0].elec.p0[1] = {-half_y - 200:g}",
        "stim[0].elec.p0[2] = -100", f"stim[0].elec.p1[0] = {-half_x + 500:g}",
        f"stim[0].elec.p1[1] = {half_y + 200:g}", "stim[0].elec.p1[2] = 100",
        "stim[0].ptcl.start = 1", f"stim[0].ptcl.duration = {p['stimulus_duration_ms']:g}",
        f"stim[0].ptcl.bcl = {bcl:g}", f"stim[0].ptcl.npls = {beats}",
        f"stim[0].pulse.strength = {p['stimulus_strength']:g}"]
    return "\n".join(lines) + "\n"


def read_igb(path: Path) -> tuple[Array, float]:
    """Voltage array of shape (time, nodes) and the output interval in ms."""
    with path.open("rb") as fh:
        header = fh.read(IGB_HEADER).decode("ascii", "ignore")
        fields = dict(tok.split(":", 1) for tok in header.split() if ":" in tok)
        nodes, steps = int(fields["x"]), int(fields["t"])
        data = np.fromfile(fh, dtype="<f4", count=nodes * steps)
    return data.reshape(steps, nodes).astype(float), float(fields["inc_t"])


def _crossings(v: Array, level: float, rising: bool) -> list[int]:
    above = v >= level
    change = np.nonzero(above[1:] != above[:-1])[0]
    return [int(i) for i in change if (above[i + 1] if rising else above[i])]


def analyse(vm: Array, dt_ms: float, p: Params, bcl: float, points: Array
            ) -> tuple[Array, Array, float]:
    """Activation time, APD90 and the activated fraction of the last paced beat."""
    beats = int(p["beats"])
    t0 = bcl * (beats - 1)
    start = int(t0 / dt_ms)
    nodes = vm.shape[1]
    act = np.full(nodes, np.nan)
    apd = np.full(nodes, np.nan)
    thr = p["activation_threshold_mv"]
    frac = p["repolarisation_fraction"]
    for j in range(nodes):
        v = vm[start:, j]
        ups = _crossings(v, thr, True)
        if not ups:
            continue
        i0 = ups[0]
        peak, rest = float(v[i0:].max()), float(vm[0, j])
        level = peak - frac * (peak - rest)
        downs = [i for i in _crossings(v[i0:], level, False)]
        t_up = (i0 + (thr - v[i0]) / (v[i0 + 1] - v[i0])) * dt_ms
        act[j] = t0 + t_up
        if downs:
            k = i0 + downs[0]
            t_dn = (k + (v[k] - level) / (v[k] - v[k + 1])) * dt_ms
            apd[j] = t_dn - t_up
    return act, apd, float(np.mean(np.isfinite(act)))


def conduction_velocity(points: Array, act: Array, length_um: float) -> float:
    """Slope of position (um) against activation time (ms) along the slab, in m/s."""
    inner = np.isfinite(act) & (np.abs(points[:, 0]) < length_um / 2 * 0.8) \
        & (points[:, 0] > -length_um / 2 * 0.8 + 2000.0)
    if inner.sum() < 5:
        return float("nan")
    slope = np.polyfit(act[inner], points[inner, 0], 1)[0]
    return float(slope) / 1000.0


def _read_points(base: Path) -> Array:
    rows = base.with_suffix(".pts").read_text().split("\n")[1:]
    return np.array([[float(x) for x in r.split()] for r in rows if r.strip()])


def _read_cells(base: Path) -> list[list[int]]:
    cells = []
    for row in base.with_suffix(".elem").read_text().split("\n")[1:]:
        parts = row.split()
        if parts and parts[0] in ("Qd", "Tr", "Tt", "Hx"):
            cells.append([int(x) for x in parts[1:-1]])
    return cells


def write_mesh_files(directory: Path, points: Array, cells: list[list[int]],
                     fields: Mapping[str, Array]) -> tuple[Path, Path]:
    """Mesh with node scalars as vtk.js JSON and as a legacy ASCII VTK polydata file."""
    mm = points / 1000.0
    payload = {"points": mm.round(5).tolist(), "polys": cells,
               "pointData": {k: [None if not np.isfinite(x) else round(float(x), 4)
                                 for x in v] for k, v in fields.items()}}
    json_path = directory / "tissue.json"
    json_path.write_text(json.dumps(payload), encoding="utf-8")
    lines = ["# vtk DataFile Version 3.0", "ATRA tissue slab", "ASCII", "DATASET POLYDATA",
             f"POINTS {len(mm)} float"]
    lines += [f"{x:.5f} {y:.5f} {z:.5f}" for x, y, z in mm]
    size = sum(len(c_) + 1 for c_ in cells)
    lines.append(f"POLYGONS {len(cells)} {size}")
    lines += [" ".join(str(i) for i in [len(c_), *c_]) for c_ in cells]
    lines.append(f"POINT_DATA {len(mm)}")
    for name, values in fields.items():
        lines += [f"SCALARS {name} float 1", "LOOKUP_TABLE default"]
        lines += [f"{(float(x) if np.isfinite(x) else -1.0):.4f}" for x in values]
    vtk_path = directory / "tissue.vtk"
    vtk_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, vtk_path


def run_job(p: Params, scenario: TissueScenario, directory: Path) -> TissueResult:
    """Mesh, simulate and analyse one scenario. Raises BackendMissing without openCARP."""
    root = backends.opencarp_root()
    backends.require(backends.opencarp())
    directory = directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    mesh = _write_mesh(root, p, directory)
    par = directory / "run.par"
    par.write_text(parameter_file(p, scenario, Path(mesh.name), "out"), encoding="utf-8")
    done = subprocess.run([str(root / "usr" / "bin" / "openCARP"), "+F", str(par)], check=False,
                          capture_output=True, text=True, env=_env(root), timeout=RUN_TIMEOUT_S,
                          cwd=directory)
    vm_path = directory / "out" / "vm.igb"
    if done.returncode != 0 or not vm_path.exists():
        raise RuntimeError(f"openCARP failed ({done.returncode}): {done.stdout[-400:]}")
    vm, dt_ms = read_igb(vm_path)
    points = _read_points(mesh)
    bcl = 60000.0 / scenario.heart_rate
    act, apd, frac = analyse(vm, dt_ms, p, bcl, points)
    repol = act + apd
    length_um = p["slab_length_cm"] * 10000.0
    cv = conduction_velocity(points, act - np.nanmin(act), length_um)
    keep = np.isfinite(apd) & (points[:, 0] > -length_um / 2 + 3000.0)
    mesh_json, mesh_vtk = write_mesh_files(
        directory, points, _read_cells(mesh),
        {"activation_ms": act - np.nanmin(act), "apd90_ms": apd})
    return TissueResult(
        apd90_ms=float(np.nanmedian(apd[keep])) if keep.any() else float("nan"),
        qt_surrogate_ms=float(np.nanmax(repol) - np.nanmin(act)),
        conduction_velocity_m_s=cv, activated_fraction=frac,
        apd90_dispersion_ms=float(np.nanmax(apd[keep]) - np.nanmin(apd[keep])) if keep.any()
        else float("nan"),
        runtime_s=time.monotonic() - started, directory=directory, mesh_json=mesh_json,
        mesh_vtk=mesh_vtk)


def single_cell_apd90(p: Params, scenario: TissueScenario) -> float:
    """APD90 of the last paced beat of one isolated cell of the same ionic model.

    The bench tool paces the cell with the stimulus of the tissue job, one beat longer so
    that the analysed beat is complete.
    """
    root = backends.opencarp_root()
    backends.require(backends.opencarp())
    bcl = 60000.0 / scenario.heart_rate
    beats = int(p["beats"])
    command = [str(root / "usr" / "bin" / "bench"), "--imp", IONIC_MODEL,
               "--stim-curr", f"{p['stimulus_strength']:g}",
               "--stim-dur", f"{p['stimulus_duration_ms']:g}", "--numstim", str(beats + 1),
               "--bcl", f"{bcl:g}", "--duration", f"{bcl * (beats + 1):g}", "--APstatistics",
               "--no-trace"]
    if scenario.im_param():
        command += ["--imp-par", scenario.im_param()]
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(command, check=True, capture_output=True, env=_env(root), cwd=tmp,
                       timeout=120)
        rows = [ln.split() for ln in (Path(tmp) / "BENCH_REG_AP_stats.dat").read_text()
                .splitlines() if ln and not ln.startswith("#")]
    return float(next(r for r in rows if int(r[0]) == beats)[3])


class CardiacElectrophysiologyModel(Layer4Base):
    spec = ModelSpec(
        model_id="ahdt.cardiovascular.conduction_system_and_cardiomyocyte_electrophysiology",
        twin=DTKind.CARDIOVASCULAR, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Action potential duration, QT surrogate and conduction velocity of "
                     "ventricular tissue, with IKr block scenarios",
        instances=("UBERON:0000948",),
        inputs=(Port("heart_rate", "/min",
                     "model:ahdt.cardiovascular.heart_chambers_and_valves#heart_rate"),
                Port("ikr_block", "1", "input:scenario")),
        outputs=(Port("apd90", "ms"), Port("qt_surrogate", "ms"),
                 Port("conduction_velocity", "m/s"), Port("apd90_dispersion", "ms")),
        explainers=("sensitivity.local", "counterfactual.scenario"),
        fidelity_note="Epicardial ten Tusscher-Panfilov cells on a 2D slab; the QT surrogate "
                      "runs from the first activation to the last repolarisation of the slab, "
                      "not of the ventricle.")
    params_stem = "opencarp"

    def initial_state(self, p: Params, inputs: Mapping[str, Any]) -> dict[str, Any]:
        cached = baselines.lookup(self.model_id, p, {})
        if cached is not None:
            return dict(cached["state"])
        return self.reference_state(p, {})

    def reference_state(self, p: Params, inputs: Mapping[str, Any]) -> dict[str, Any]:
        result = self.run_scenario(p, inputs, self.work_dir("reference"))
        return self.values_of(result)

    @staticmethod
    def values_of(result: TissueResult) -> dict[str, float]:
        return {"apd90": result.apd90_ms, "qt_surrogate": result.qt_surrogate_ms,
                "conduction_velocity": result.conduction_velocity_m_s,
                "apd90_dispersion": result.apd90_dispersion_ms}

    def work_dir(self, name: str) -> Path:
        return sources.directory().parent / "jobs" / "opencarp" / name

    def run_scenario(self, p: Params, inputs: Mapping[str, Any], directory: Path
                     ) -> TissueResult:
        scenario = TissueScenario(heart_rate=float(inputs.get("heart_rate", 60.0)),
                                  ikr_block=float(inputs.get("ikr_block", 0.0)))
        return run_job(p, scenario, directory)

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Mapping[str, Any]
                 ) -> dict[str, Any]:
        if not inputs:
            have = self.initial_state(p, {})
            have.update({k: float(v) for k, v in state.items() if k in have})
            return have
        key = baselines.fingerprint(p, inputs)
        directory = self.work_dir(key)
        return self.values_of(self.run_scenario(p, inputs, directory))

    async def predict(self, inputs: Mapping[str, Any], state: c.InstanceRecord | None
                      ) -> c.ModelOutput:
        p = self.parameters(state)
        current = dict(state.state) if state is not None else self.initial_state(p, inputs)
        values = await asyncio.to_thread(self.evaluate, p, current, inputs)
        return self._output(state, inputs, values)

    def baseline(self) -> baselines.Entry:
        p = self.parameters()
        state = self.reference_state(p, {})
        return {"fingerprint": baselines.fingerprint(p, {}), "state": state, "outputs": state,
                "backend": f"openCARP {backends.opencarp().version}, {IONIC_MODEL}"}
