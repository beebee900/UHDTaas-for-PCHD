"""Aortic segment: 1D blood flow solved by a physics-informed neural network (DeepXDE).

The equations are those of Kissas et al. (2020), eq. (1): conservation of mass and momentum
for the area A and the velocity u, with the thin-wall pressure law p = p_ext + beta (sqrt(A) -
sqrt(A0)). The friction term uses K_R = -22 pi mu / rho. The inlet velocity follows a
half-sine ejection pulse scaled by the stroke volume factor `s`, the outlet is non-reflecting
(constant backward Riemann invariant), and the segment starts at rest. The network takes
(x/L, t/T, s) and returns (A/A0 - 1, u/U), so one trained network serves stroke volumes
from 0.5 to 1.5 times the reference.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.base import Layer4Base, ModelSpec, Params, Port
from ahdt.models.external import backends
from atra import contracts as c
from atra.config import ROOT
from atra.connectors import DTKind

os.environ.setdefault("DDE_BACKEND", "pytorch")

MMHG_PA = 133.322
VELOCITY_SCALE = 0.5
AREA_SCALE = 1.0
S_RANGE = (0.5, 1.5)
HIDDEN = (64, 64, 64, 64)
MODEL_DIR = ROOT / "var" / "models" / "wp14c-aorta-pinn"


class Geometry:
    """Derived constants of the segment."""

    def __init__(self, p: Mapping[str, float]) -> None:
        self.p = dict(p)
        self.a0 = math.pi * (p["diameter_m"] / 2) ** 2
        self.length = p["length_m"]
        self.period = p["period_s"]
        self.c0 = p["wave_speed"]
        self.beta = 2 * p["rho"] * self.c0 ** 2 / math.sqrt(self.a0)
        self.q_max = math.pi * p["stroke_volume_ml"] * 1e-6 / (2 * p["systole_s"])
        self.nu = p["mu"] / p["rho"]

    def inflow_velocity(self, t: Array, s: float | Array = 1.0) -> Array:
        ts = self.p["systole_s"]
        q = np.where((t >= 0) & (t <= ts), self.q_max * np.sin(math.pi * t / ts), 0.0)
        return np.asarray(s * q / self.a0)

    def pressure_mmhg(self, a_rel: Array) -> Array:
        """Pressure above the diastolic value in mmHg."""
        return np.asarray(self.beta * (np.sqrt(1.0 + a_rel) - 1.0) * math.sqrt(self.a0)
                          / MMHG_PA)

    @property
    def compliance_ml_per_mmhg(self) -> float:
        return self.length * self.a0 / (self.p["rho"] * self.c0 ** 2) * 1e6 * MMHG_PA

    @property
    def impedance_mmhg_s_per_ml(self) -> float:
        return self.p["rho"] * self.c0 / self.a0 / (MMHG_PA * 1e6)


def reference_solution(g: Geometry, s: float = 1.0, nx: int = 400, cfl: float = 0.4
                       ) -> tuple[Array, Array, Array, Array]:
    """Lax-Friedrichs solution of the same equations: x (m), t (s), a(x,t), u(x,t)."""
    p = g.p
    alpha = p["alpha"]
    dx = g.length / (nx - 1)
    x = np.linspace(0, g.length, nx)
    a = np.ones(nx)          # A / A0
    u = np.zeros(nx)
    t = 0.0
    times, a_hist, u_hist = [0.0], [a - 1.0], [u.copy()]
    sample = g.period / 200
    next_sample = sample
    k = 22 * math.pi * g.nu / g.a0
    sqrt_a0 = math.sqrt(g.a0)
    while t < g.period:
        c = g.c0 * a ** 0.25
        dt = cfl * dx / float(np.max(np.abs(u) + c))
        dt = min(dt, g.period - t)
        flux_a = a * u
        # momentum in primitive form, with the viscous term k u / a
        a_new = a.copy()
        u_new = u.copy()
        dad = np.gradient(a, dx)
        dud = np.gradient(u, dx)
        dfa = np.gradient(flux_a, dx)
        rhs_a = -dfa
        rhs_u = (-alpha * u * dud - (alpha - 1) * u / a * np.gradient(u * a, dx)
                 - g.beta * sqrt_a0 / (2 * p["rho"]) * dad / np.sqrt(a) - k * u / a)
        a_new[1:-1] = 0.5 * (a[2:] + a[:-2]) + dt * rhs_a[1:-1]
        u_new[1:-1] = 0.5 * (u[2:] + u[:-2]) + dt * rhs_u[1:-1]
        t += dt
        u_new[0] = float(g.inflow_velocity(np.array(t), s))
        a_new[0] = a_new[1]
        a_new[-1] = a_new[-2]
        u_new[-1] = 4 * g.c0 * (a_new[-1] ** 0.25 - 1.0)
        a, u = a_new, u_new
        if t >= next_sample:
            times.append(t)
            a_hist.append(a - 1.0)
            u_hist.append(u.copy())
            next_sample += sample
    return x, np.array(times), np.array(a_hist), np.array(u_hist)


def foot_to_foot_speed(g: Geometry, nx: int = 200) -> float:
    """Pulse wave speed from the arrival of the pressure foot at 10 and 90 percent of the length."""
    x, t, a, _ = reference_solution(g, 1.0, nx=nx)

    def foot(column: Array) -> float:
        return float(t[int(np.argmax(column > 0.05 * column.max()))])

    near, far = int(0.1 * (nx - 1)), int(0.9 * (nx - 1))
    return float((x[far] - x[near]) / (foot(a[:, far]) - foot(a[:, near])))


def build(g: Geometry) -> Any:
    backends.require(backends.deepxde())
    import deepxde as dde
    import torch

    length, period = g.length, g.period
    ut_over_l = VELOCITY_SCALE * period / length
    alpha, k = g.p["alpha"], 22 * math.pi * g.nu * period / g.a0
    stiff = period * g.beta * math.sqrt(g.a0) / (2 * g.p["rho"] * length * VELOCITY_SCALE)

    def pde(x: Any, y: Any) -> list[Any]:
        a, v = y[:, 0:1], y[:, 1:2]
        a_t = dde.grad.jacobian(y, x, i=0, j=1)
        a_x = dde.grad.jacobian(y, x, i=0, j=0)
        v_t = dde.grad.jacobian(y, x, i=1, j=1)
        v_x = dde.grad.jacobian(y, x, i=1, j=0)
        w = 1.0 + a
        mass = a_t + ut_over_l * (w * v_x + v * a_x)
        momentum = (v_t + alpha * ut_over_l * v * v_x
                    + (alpha - 1) * ut_over_l * v / w * (w * v_x + v * a_x)
                    + stiff * a_x / torch.sqrt(w) + k * v / w)
        return [mass, momentum]

    box = dde.geometry.Cuboid([0.0, 0.0, S_RANGE[0]], [1.0, 1.0, S_RANGE[1]])

    def inlet(x: Any, on_boundary: bool) -> bool:
        return bool(on_boundary and np.isclose(x[0], 0.0))

    def outlet(x: Any, on_boundary: bool) -> bool:
        return bool(on_boundary and np.isclose(x[0], 1.0))

    def initial(x: Any, on_boundary: bool) -> bool:
        return bool(on_boundary and np.isclose(x[1], 0.0))

    def inlet_value(x: Any) -> Any:
        return g.inflow_velocity(x[:, 1:2] * period, x[:, 2:3]) / VELOCITY_SCALE

    def outlet_residual(inputs: Any, outputs: Any, _x: Any) -> Any:
        a, v = outputs[:, 0:1], outputs[:, 1:2]
        return v * VELOCITY_SCALE - 4 * g.c0 * ((1.0 + a) ** 0.25 - 1.0)

    bcs = [dde.icbc.DirichletBC(box, inlet_value, inlet, component=1),
           dde.icbc.OperatorBC(box, outlet_residual, outlet),
           dde.icbc.DirichletBC(box, lambda x: 0.0, initial, component=0),
           dde.icbc.DirichletBC(box, lambda x: 0.0, initial, component=1)]
    data = dde.data.PDE(box, pde, bcs, num_domain=6000, num_boundary=1200,
                        num_test=2000)
    net = dde.nn.FNN([3, *HIDDEN, 2], "tanh", "Glorot normal")
    return dde.Model(data, net)


def compare(model: Any, g: Geometry, s: float = 1.0) -> dict[str, float]:
    """Relative L2 error of the network against the finite-difference solution."""
    x, t, a_ref, u_ref = reference_solution(g, s)
    xi, ti = np.meshgrid(x / g.length, t / g.period)
    a, u = predict(model, g, xi, ti, s)
    return {"area_rel_l2": float(np.linalg.norm(a - a_ref) / np.linalg.norm(a_ref)),
            "velocity_rel_l2": float(np.linalg.norm(u - u_ref) / np.linalg.norm(u_ref)),
            "stroke_volume_factor": s}


def train(g: Geometry, adam_iterations: int = 8000, lbfgs_iterations: int = 2000,
          seed: int = 1, log: Path | None = None) -> dict[str, Any]:
    import deepxde as dde

    dde.config.set_random_seed(seed)
    model = build(g)
    weights = [1, 1, 20, 20, 20, 20]
    model.compile("adam", lr=1e-3, loss_weights=weights)
    history, _ = model.train(iterations=adam_iterations, display_every=1000)
    if lbfgs_iterations > 0:
        dde.optimizers.set_LBFGS_options(maxiter=lbfgs_iterations)
        model.compile("L-BFGS", loss_weights=weights)
        history, _ = model.train()
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    saved = model.save(str(MODEL_DIR / "aorta"))
    weights_file = Path(saved)
    errors = [compare(model, g, s) for s in (0.7, 1.0, 1.3)]
    meta = {"weights": weights_file.name,
            "sha256": hashlib.sha256(weights_file.read_bytes()).hexdigest(),
            "bytes": weights_file.stat().st_size, "params": g.p,
            "adam_iterations": adam_iterations, "lbfgs_iterations": lbfgs_iterations,
            "seed": seed, "final_loss": [float(x) for x in history.loss_train[-1]],
            "validation": errors, "deepxde": backends.deepxde().version}
    (MODEL_DIR / "meta.json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    if log is not None:
        log.write_text(json.dumps(meta), encoding="utf-8")
    return meta


_LOADED: dict[str, Any] = {}


def load(g: Geometry) -> Any:
    """The trained network, restored once per process. The geometry must be the trained one."""
    meta = json.loads((MODEL_DIR / "meta.json").read_text(encoding="utf-8"))
    if any(not abs(meta["params"].get(k, math.inf) - v) <= 1e-12 for k, v in g.p.items()):
        raise RuntimeError("the aorta PINN was trained for other parameters")
    if meta["sha256"] not in _LOADED:
        weights = MODEL_DIR / meta["weights"]
        if hashlib.sha256(weights.read_bytes()).hexdigest() != meta["sha256"]:
            raise RuntimeError("aorta PINN weights do not match their recorded sha256")
        model = build(g)
        model.compile("L-BFGS" if meta["lbfgs_iterations"] > 0 else "adam", lr=1e-3)
        model.restore(str(weights))
        _LOADED[meta["sha256"]] = model
    return _LOADED[meta["sha256"]]


def predict(model: Any, g: Geometry, x_rel: Array, t_rel: Array, s: float = 1.0
            ) -> tuple[Array, Array]:
    """a(x,t) = A/A0 - 1 and u(x,t) in m/s on matching arrays of positions and times."""
    pts = np.column_stack([x_rel.ravel(), t_rel.ravel(), np.full(x_rel.size, s)])
    out = model.predict(pts)
    return out[:, 0].reshape(x_rel.shape), out[:, 1].reshape(x_rel.shape) * VELOCITY_SCALE


class AortaModel(Layer4Base):
    spec = ModelSpec(
        model_id="ahdt.cardiovascular.aorta",
        twin=DTKind.CARDIOVASCULAR, family=c.ModelFamily.PHYSICS_HYBRID, tier=c.Tier.T2,
        intended_use="Pulse pressure, pulse wave speed and vascular resistance and compliance of "
                     "an aortic segment for one cardiac cycle",
        instances=("UBERON:0000947",),
        inputs=(Port("stroke_volume", "mL",
                     "model:ahdt.cardiovascular.heart_chambers_and_valves#stroke_volume"),),
        outputs=(Port("pulse_pressure", "mm[Hg]"), Port("pulse_wave_speed", "m/s"),
                 Port("resistance", "mm[Hg].s/mL"), Port("compliance", "mL/mm[Hg]"),
                 Port("peak_velocity", "m/s")),
        explainers=("sensitivity.local",),
        fidelity_note="One segment and one cardiac cycle at 70 beats per minute. Wall stiffness "
                      "follows from an assumed wave speed.")
    params_stem = "aorta"

    def geometry(self, p: Params) -> Geometry:
        return Geometry(p)

    def initial_state(self, p: Params, inputs: Mapping[str, Any]) -> dict[str, Any]:
        g = self.geometry(p)
        return {"resistance": g.impedance_mmhg_s_per_ml,
                "compliance": g.compliance_ml_per_mmhg, "pulse_wave_speed": g.c0}

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Mapping[str, Any]
                 ) -> dict[str, Any]:
        g = self.geometry(p)
        out = self.initial_state(p, inputs)
        out.update({k: float(v) for k, v in state.items() if k in ("pulse_pressure",
                                                                   "peak_velocity")})
        if "stroke_volume" in inputs:
            s = float(inputs["stroke_volume"]) / g.p["stroke_volume_ml"]
            out.update(self.beat(g, s))
        return out

    def beat(self, g: Geometry, s: float) -> dict[str, float]:
        if not S_RANGE[0] <= s <= S_RANGE[1]:
            raise ValueError(f"stroke volume factor {s:.2f} is outside the trained range")
        model = load(g)
        x = np.full(200, 0.5)
        t = np.linspace(0, 1, 200)
        a, u = predict(model, g, x, t, s)
        pressure = g.pressure_mmhg(a)
        return {"pulse_pressure": float(pressure.max() - pressure.min()),
                "peak_velocity": float(np.abs(u).max())}


def main() -> None:
    import argparse

    from ahdt.models.params import load_params, params_path

    parser = argparse.ArgumentParser(description="Train the aorta PINN and store its weights")
    parser.add_argument("--adam", type=int, default=8000)
    parser.add_argument("--lbfgs", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=1)
    args = parser.parse_args()
    params = load_params(params_path(__file__, "aorta")).values
    meta = train(Geometry(params), args.adam, args.lbfgs, args.seed)
    print(json.dumps({k: meta[k] for k in ("weights", "sha256", "final_loss", "validation")}))


if __name__ == "__main__":
    main()
