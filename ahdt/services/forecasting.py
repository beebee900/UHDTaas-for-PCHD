"""Damped-trend forecaster for a person's own measurement series (design 04, 4.7.3).

The series is resampled to a regular grid. Holt's damped additive trend is fitted to the
grid by least squares over the smoothing constants. The 90 % band is the empirical quantile
of the one-step fit residuals, widened with the square root of the step ahead, as for a
random walk. It is a baseline forecaster for the twin fields that have no trained model.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from scipy.optimize import minimize

type F = NDArray[np.float64]

LEVEL = 0.9
MIN_POINTS = 6
MAX_GRID = 400
VERSION = "1.0.0"


@dataclass(frozen=True)
class Fit:
    alpha: float
    beta: float
    phi: float
    level: float
    trend: float
    sigma: float
    residuals: F


def regular_grid(times_h: Sequence[float], values: Sequence[float]) -> tuple[F, float]:
    """Values on an even grid (linear interpolation) and the grid step in hours."""
    t = np.asarray(times_h, dtype=float)
    v = np.asarray(values, dtype=float)
    if len(t) < 2:
        raise ValueError("a series needs at least two points")
    step = float(np.median(np.diff(t)))
    if step <= 0:
        step = (t[-1] - t[0]) / (len(t) - 1) or 1.0
    n = min(round((t[-1] - t[0]) / step) + 1, MAX_GRID)
    step = (t[-1] - t[0]) / (n - 1)
    grid = np.linspace(t[0], t[-1], n)
    out: F = np.interp(grid, t, v)
    return out, step


def _run(y: F, alpha: float, beta: float, phi: float) -> tuple[float, float, F]:
    level, trend = float(y[0]), float(y[1] - y[0])
    errors = np.empty(len(y) - 1)
    for i in range(1, len(y)):
        pred = level + phi * trend
        errors[i - 1] = y[i] - pred
        new_level = pred + alpha * errors[i - 1]
        trend = phi * trend + alpha * beta * errors[i - 1]
        level = new_level
    return level, trend, errors


def fit(y: F) -> Fit:
    if len(y) < MIN_POINTS:
        raise ValueError(f"a forecast needs at least {MIN_POINTS} points")

    def sse(theta: F) -> float:
        a, b, p = theta
        return float(np.sum(_run(y, a, b, p)[2] ** 2))

    best = minimize(sse, np.array([0.5, 0.2, 0.9]), method="L-BFGS-B",
                    bounds=[(0.01, 0.99), (0.01, 0.99), (0.8, 0.98)])
    a, b, p = (float(x) for x in best.x)
    level, trend, errors = _run(y, a, b, p)
    return Fit(a, b, p, level, trend, float(errors.std()), errors)


def forecast(f: Fit, steps: int) -> tuple[F, F]:
    """Mean and half-width of the 90 % band for steps 1..`steps` ahead."""
    mean = np.empty(steps)
    damp = 0.0
    for h in range(1, steps + 1):
        damp += f.phi ** h
        mean[h - 1] = f.level + damp * f.trend
    q = float(np.quantile(np.abs(f.residuals), LEVEL)) if len(f.residuals) else f.sigma
    half = q * np.sqrt(np.arange(1, steps + 1))
    return mean, half


def predict_batch(windows: Sequence[F], steps: int) -> F:
    """Mean forecasts of each (n, 1) window, shaped (windows, steps, 1)."""
    out = np.empty((len(windows), steps, 1))
    for i, w in enumerate(windows):
        out[i, :, 0] = forecast(fit(np.asarray(w, dtype=float).reshape(-1)), steps)[0]
    return out


def ahead(horizon_h: float, step_h: float) -> int:
    return max(1, math.ceil(horizon_h / step_h))
