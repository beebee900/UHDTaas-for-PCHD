"""FMU export and co-simulation of the cardiovascular, respiratory and renal models.

`build_fmus` builds the three slaves of `cosim_fmus` into FMI 2.0 FMUs with pythonfmu.
`run_cosimulation` is a Jacobi fixed-step master written on the FMPy FMU interface: at each
communication point every FMU gets the outputs the others had at the previous point, then
all FMUs step together. `run_reference` runs the same models in one process with the exact
coupled variable of the current step, the uncoupled reference of the acceptance test.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.external import backends
from atra.config import ROOT

FMU_DIR = ROOT / "var" / "wp14c" / "fmus"
SLAVES = {"Cardiovascular": "CardiovascularSlave", "Respiratory": "RespiratorySlave",
          "Renal": "RenalSlave"}
# (producer, output) -> [(consumer, input)]
COUPLINGS: Mapping[tuple[str, str], list[tuple[str, str]]] = {
    ("Cardiovascular", "cardiac_output"): [("Respiratory", "cardiac_output"),
                                           ("Renal", "cardiac_output")]}
type Drive = Callable[[float], float]


def _script(name: str, slave: str) -> str:
    return (f"import sys\nsys.path.insert(0, {str(ROOT)!r})\n"
            f"from ahdt.models.external.cosim_fmus import {slave}  # noqa: F401\n")


def build_fmus(directory: Path = FMU_DIR) -> dict[str, Path]:
    backends.require(backends.pythonfmu())
    directory.mkdir(parents=True, exist_ok=True)
    built: dict[str, Path] = {}
    with tempfile.TemporaryDirectory() as tmp:
        for name, slave in SLAVES.items():
            script = Path(tmp) / f"{name.lower()}_slave.py"
            script.write_text(_script(name, slave), encoding="utf-8")
            target = directory / f"{name}.fmu"
            done = subprocess.run(
                [sys.executable, "-m", "pythonfmu", "build", "-f", str(script), "-d", tmp],
                check=False, capture_output=True, text=True, cwd=tmp)
            produced = Path(tmp) / f"{script.stem.replace('_slave', '')}_slave.fmu"
            fmus = list(Path(tmp).glob("*.fmu"))
            if done.returncode != 0 or not fmus:
                raise RuntimeError(f"pythonfmu failed for {name}: {done.stderr[-500:]}")
            shutil.move(str(fmus[0] if not produced.exists() else produced), target)
            built[name] = target
    return built


@dataclass
class Trajectory:
    t: Array
    values: dict[str, Array]


def run_cosimulation(fmus: Mapping[str, Path], drives: Mapping[tuple[str, str], Drive],
                     stop_s: float, step_s: float) -> Trajectory:
    """Jacobi master. `drives` maps (fmu, input) to the external input as a function of time.

    The master runs in its own interpreter: an FMU built by pythonfmu embeds Python and cannot
    be instantiated twice in one process. The drives are sampled at the communication points.
    """
    backends.require(backends.fmpy())
    times = np.arange(0.0, stop_s + step_s / 2, step_s)
    job = {"fmus": {n: str(p) for n, p in fmus.items()}, "step_s": step_s,
           "times": times.tolist(),
           "drives": [[n, v, [fn(float(t)) for t in times]] for (n, v), fn in drives.items()]}
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([str(ROOT), env.get("PYTHONPATH", "")])
    done = subprocess.run([sys.executable, "-m", "ahdt.models.external.cosim"], check=False,
                          input=json.dumps(job), capture_output=True, text=True, env=env,
                          cwd=ROOT, timeout=600)
    if done.returncode != 0:
        raise RuntimeError(f"co-simulation failed ({done.returncode}): {done.stderr[-500:]}")
    values = json.loads(done.stdout)
    return Trajectory(times, {k: np.array(v) for k, v in values.items()})


def _master(job: Mapping[str, Any]) -> dict[str, list[float]]:
    from fmpy import extract, read_model_description
    from fmpy.fmi2 import FMU2Slave

    step_s = float(job["step_s"])
    times = job["times"]
    series = {(n, v): values for n, v, values in job["drives"]}
    slaves: dict[str, FMU2Slave] = {}
    refs: dict[str, dict[str, int]] = {}
    dirs = []
    try:
        for name, path in job["fmus"].items():
            desc = read_model_description(path)
            unzip = extract(path)
            dirs.append(unzip)
            refs[name] = {v.name: v.valueReference for v in desc.modelVariables}
            slave = FMU2Slave(guid=desc.guid, unzipDirectory=unzip,
                              modelIdentifier=desc.coSimulation.modelIdentifier,
                              instanceName=name)
            slave.instantiate()
            slave.setupExperiment(startTime=0.0)
            slave.enterInitializationMode()
            slaves[name] = slave
        for (name, var), values in series.items():
            slaves[name].setReal([refs[name][var]], [values[0]])
        for slave in slaves.values():
            slave.exitInitializationMode()
        rows: dict[str, list[float]] = {}

        def record() -> None:
            for n, slave in slaves.items():
                for var, ref in refs[n].items():
                    rows.setdefault(f"{n}.{var}", []).append(slave.getReal([ref])[0])

        record()
        for k, t in enumerate(times[:-1]):
            carried = {(cn, ci): slaves[pn].getReal([refs[pn][po]])[0]
                       for (pn, po), cs in COUPLINGS.items() for cn, ci in cs}
            for (n, var), values in series.items():
                slaves[n].setReal([refs[n][var]], [values[k]])
            for (cn, ci), value in carried.items():
                slaves[cn].setReal([refs[cn][ci]], [value])
            for slave in slaves.values():
                slave.doStep(currentCommunicationPoint=float(t), communicationStepSize=step_s)
            record()
        return rows
    finally:
        for slave in slaves.values():
            slave.terminate()
        for d in dirs:
            shutil.rmtree(d, ignore_errors=True)


def main() -> None:
    """Worker entry: read the job from stdin, write the recorded variables to stdout."""
    job = json.loads(sys.stdin.read())
    sys.stdout.write(json.dumps(_master(job)))
    sys.stdout.flush()
    os._exit(0)  # the FMUs' embedded interpreters cannot be finalised in this process


def _held(u: Mapping[str, float]) -> Callable[[float], Mapping[str, float]]:
    return lambda _t: u


def run_reference(drives: Mapping[tuple[str, str], Drive], stop_s: float, step_s: float
                  ) -> Trajectory:
    """The same models in one process; each step uses the cardiac output of the same time."""
    from ahdt.models.cardiovascular.heart import HeartModel
    from ahdt.models.renal_urinary.kidney import KidneyModel
    from ahdt.models.respiratory.ventilation import VentilationControlModel

    heart, vent, kidney = HeartModel(), VentilationControlModel(), KidneyModel()
    hp, vp, kp = heart.parameters(), vent.parameters(), kidney.parameters()
    hs = heart.initial_state(hp, {})
    times = np.arange(0.0, stop_s + step_s / 2, step_s)

    def co_at(t: float) -> dict[str, float]:
        hr = drives[("Cardiovascular", "heart_rate")](t)
        return heart.evaluate(hp, hs, {"heart_rate": round(hr, 3)})

    co0 = co_at(0.0)["cardiac_output"]
    fio2_0 = drives[("Respiratory", "fio2")](0.0)
    yv = np.array([vent.initial_state(vp, {"fio2": fio2_0, "cardiac_output": co0})[n]
                   for n in vent.state_names])
    yk = np.array([kidney.initial_state(kp, {})[n] for n in kidney.state_names])
    rows: dict[str, list[float]] = {}

    def add(key: str, value: float) -> None:
        rows.setdefault(key, []).append(float(value))

    def record(t: float, co: float, ov: Mapping[str, float], ok: Mapping[str, float],
               h: Mapping[str, float]) -> None:
        add("Cardiovascular.heart_rate", drives[("Cardiovascular", "heart_rate")](t))
        add("Cardiovascular.cardiac_output", h["cardiac_output"])
        add("Cardiovascular.map", h["map"])
        add("Cardiovascular.sbp", h["sbp"])
        add("Cardiovascular.dbp", h["dbp"])
        add("Respiratory.fio2", drives[("Respiratory", "fio2")](t))
        add("Respiratory.cardiac_output", co)
        for k in ("minute_ventilation", "paco2", "pao2"):
            add(f"Respiratory.{k}", ov[k])
        add("Renal.cardiac_output", co)
        for k in ("creatinine", "egfr", "filtration_fraction"):
            add(f"Renal.{k}", ok[k])

    h = co_at(0.0)
    co = h["cardiac_output"]
    ov = vent.observe(0.0, yv, vp, {"fio2": fio2_0, "cardiac_output": co})
    ok = kidney.observe(0.0, yk, kp, {"cardiac_output": co})
    record(0.0, co, ov, ok, h)
    for t in times[:-1]:
        h = co_at(float(t))
        co = h["cardiac_output"]
        fio2 = drives[("Respiratory", "fio2")](float(t))
        uv = {"fio2": fio2, "cardiac_output": co}
        yv = np.asarray(vent.integrate(vp, yv, np.array([0.0, step_s]), _held(uv))[-1])
        uk = {"cardiac_output": co}
        yk = np.asarray(kidney.integrate(kp, yk, np.array([0.0, step_s / kidney.time_scale_s]),
                                         _held(uk))[-1])
        h_next = co_at(float(t + step_s))
        ov = vent.observe(0.0, yv, vp, uv)
        ok = kidney.observe(0.0, yk, kp, uk)
        record(float(t + step_s), co, ov, ok, h_next)
    return Trajectory(times, {k: np.array(v) for k, v in rows.items()})


if __name__ == "__main__":
    main()
