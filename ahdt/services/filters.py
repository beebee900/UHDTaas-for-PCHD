"""Data assimilation with an unscented Kalman filter (design 04, 4.7.3).

`ukf_assimilate` carries the state vector of an ODE organ model through a person's
observations. Between observations the sigma points are integrated by the model; at each
observation the filter updates them with the observed outputs of `spec.obs_map`. The result
is the instance record with the filtered state, the state's standard deviations in
`uncertainty` and `last_assimilated` set to the last observation. Process noise is a
fraction of the state per model time unit (`PROCESS_CV`) and measurement noise is
`DEFAULT_OBS_CV` of each observed value.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any

import numpy as np
from filterpy.kalman import MerweScaledSigmaPoints, UnscentedKalmanFilter

from ahdt.models.arrays import Array
from ahdt.models.base import DEFAULT_OBS_CV, OdeModel
from atra import contracts as c

PROCESS_CV = 0.01
INITIAL_CV = 0.1
FLOOR = 1e-6


def ukf_assimilate(model: OdeModel, record: c.InstanceRecord,
                   obs: Sequence[c.ObservationRecord], *, inputs: dict[str, Any] | None = None
                   ) -> c.InstanceRecord:
    """The record after filtering `obs` (observations of mapped outputs, any order)."""
    points = sorted(((o.effective_time, model.spec.obs_map[o.code.code], float(o.value))
                     for o in obs
                     if o.code.code in model.spec.obs_map
                     and isinstance(o.value, int | float) and not isinstance(o.value, bool)),
                    key=lambda p: p[0])
    if not points:
        return record
    p = model.parameters(record)
    u = model.drive(None, dict(inputs or {}))
    x0 = np.asarray(model.vector(record.state, p, dict(inputs or {})), dtype=float)
    n = len(x0)
    names = sorted({name for _, name, _ in points})
    sigma = MerweScaledSigmaPoints(n, alpha=0.5, beta=2.0, kappa=0.0)

    def fx(x: Array, dt: float) -> Array:
        ys = model.integrate(p, x, np.array([0.0, dt]), u)
        out: Array = np.asarray(ys[-1], dtype=float)
        return out

    def hx(x: Array) -> Array:
        seen = model.observe(0.0, x, p, u(0.0))
        return np.array([float(seen[name]) for name in names])

    ukf = UnscentedKalmanFilter(dim_x=n, dim_z=len(names), dt=1.0, hx=hx, fx=fx, points=sigma)
    ukf.x = x0
    ukf.P = np.diag((INITIAL_CV * np.maximum(np.abs(x0), FLOOR)) ** 2)
    start = record.last_assimilated or points[0][0]
    clock = start
    scale = model.time_scale_s
    for when, name, value in points:
        dt = max((when - clock).total_seconds() / scale, 0.0)
        if dt > 0:
            ukf.Q = np.diag((PROCESS_CV * np.maximum(np.abs(ukf.x), FLOOR)) ** 2 * dt)
            ukf.predict(dt=dt)
            clock = when
        z = np.full(len(names), np.nan)
        z[names.index(name)] = value
        keep = ~np.isnan(z)
        r = np.diag([max(abs(v) * DEFAULT_OBS_CV, FLOOR) ** 2 for v in z[keep]])
        _update(ukf, z, keep, r, hx)
    state = dict(record.state)
    state.update({k: float(v) for k, v in zip(model.state_names, ukf.x, strict=True)})
    state.update(model.observe(0.0, ukf.x, p, u(0.0)))
    sd = np.sqrt(np.clip(np.diag(ukf.P), 0.0, None))
    uncertainty = dict(record.uncertainty)
    uncertainty.update({k: {"std": float(s)} for k, s in zip(model.state_names, sd, strict=True)
                        if math.isfinite(float(s))})
    return record.model_copy(update={"state": state, "uncertainty": uncertainty,
                                     "last_assimilated": points[-1][0]})


def _update(ukf: UnscentedKalmanFilter, z: Array, keep: Array, r: Array, hx: Any) -> None:
    """Update with the observed components of `z` only."""
    idx = np.flatnonzero(keep)
    ukf.dim_z = len(idx)
    ukf.R = r
    ukf.update(z[idx], hx=lambda x: hx(x)[idx])
