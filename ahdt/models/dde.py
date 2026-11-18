"""Fixed-step integration of delay differential equations.

Used by the models whose published form has pure time delays (the Ursino baroreflex
effectors and the Hoshen within-host malaria model). Delayed states are read from the
stored solution by linear interpolation; before time zero they come from `history`, which
defaults to the initial state.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

import numpy as np

from ahdt.models.arrays import Array

type Lagged = Callable[[float], Array]
type DelayRhs = Callable[[float, Array, Lagged], Sequence[float]]


def integrate_dde(f: DelayRhs, y0: Array, t_eval: Array, h: float, *,
                  kicks: Sequence[tuple[float, Callable[[Array], None]]] = (),
                  history: Lagged | None = None) -> Array:
    """Fourth-order Runge-Kutta with step `h`; returns the state at each `t_eval` point.

    `f(t, y, lag)` gives dy/dt, where `lag(s)` is the state at time s <= t. Each kick
    `(t, apply)` modifies the state in place when the integration reaches time t.
    """
    t_end = float(t_eval[-1]) if len(t_eval) else 0.0
    n_steps = max(1, int(np.ceil(t_end / h)))
    h = t_end / n_steps if t_end > 0 else h
    times = np.linspace(0.0, n_steps * h, n_steps + 1)
    ys = np.empty((n_steps + 1, len(y0)))
    ys[0] = y0
    pending = sorted(kicks, key=lambda k: k[0])
    k = 0
    while k < len(pending) and pending[k][0] <= 0:
        pending[k][1](ys[0])
        k += 1
    last = 0

    def lag(s: float) -> Array:
        if s < 0 and history is not None:
            return history(s)
        if s <= 0:
            row: Array = ys[0]
            return row
        i = min(int(s / h), last)
        if i >= last:
            row = ys[last]
            return row
        w = (s - times[i]) / h
        mixed: Array = (1 - w) * ys[i] + w * ys[i + 1]
        return mixed

    for i in range(n_steps):
        t, y = times[i], ys[i]
        k1 = np.asarray(f(t, y, lag))
        k2 = np.asarray(f(t + h / 2, y + h / 2 * k1, lag))
        k3 = np.asarray(f(t + h / 2, y + h / 2 * k2, lag))
        k4 = np.asarray(f(t + h, y + h * k3, lag))
        ys[i + 1] = y + h / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        last = i + 1
        while k < len(pending) and pending[k][0] <= times[i + 1]:
            pending[k][1](ys[i + 1])
            k += 1
    out = np.empty((len(t_eval), len(y0)))
    for j, t in enumerate(t_eval):
        out[j] = [np.interp(t, times, ys[:, c]) for c in range(len(y0))]
    return out
