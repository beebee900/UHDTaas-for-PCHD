"""Individual human mobility as a Mesa model: exploration and preferential return.

The walker follows Song et al. (2010, Nature Physics 6:818): after a waiting time drawn from
P(dt) ~ dt^-(1+beta), it explores a new location with probability rho * S^-gamma, at a distance
drawn from P(dr) ~ dr^-(1+alpha) and in a random direction. Otherwise it returns to a visited
location with probability proportional to its past visits. S is the number of locations
visited so far. `fit_trace` estimates the parameters from a GPS stay-point trace.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise

import mesa
import numpy as np
from scipy.optimize import minimize

from ahdt.models.arrays import Array

EARTH_RADIUS_KM = 6371.0088


def pareto(rng: np.random.Generator, exponent: float, lo: float, hi: float) -> float:
    """A draw from the density x^-(1+exponent) truncated to [lo, hi]."""
    u = rng.random()
    a = lo ** -exponent
    b = hi ** -exponent
    return float((a - u * (a - b)) ** (-1.0 / exponent))


class Walker(mesa.Agent):
    def __init__(self, model: MobilityModel) -> None:
        super().__init__(model)
        self.locations: list[tuple[float, float]] = [(0.0, 0.0)]
        self.visits: list[int] = [1]
        self.current = 0
        self.next_move_h = 0.0
        self.trace: list[tuple[float, float, float]] = [(0.0, 0.0, 0.0)]

    def step(self) -> None:
        m: MobilityModel = self.model
        if m.hour < self.next_move_h:
            return
        p = m.p
        s = len(self.locations)
        if m.rng.random() < min(1.0, p["rho"] * s ** -p["gamma"]):
            r = pareto(m.rng, p["alpha"], p["min_jump_km"], p["max_jump_km"])
            angle = m.rng.uniform(0, 2 * math.pi)
            x, y = self.locations[self.current]
            self.locations.append((x + r * math.cos(angle), y + r * math.sin(angle)))
            self.visits.append(1)
            self.current = s
        else:
            weights = np.asarray(self.visits, dtype=float)
            self.current = int(m.rng.choice(s, p=weights / weights.sum()))
            self.visits[self.current] += 1
        x, y = self.locations[self.current]
        self.trace.append((m.hour, x, y))
        self.next_move_h = m.hour + pareto(m.rng, p["beta"], p["min_wait_h"], p["max_wait_h"])


class MobilityModel(mesa.Model):
    def __init__(self, p: Mapping[str, float], seed: int, people: int = 1) -> None:
        super().__init__(rng=seed)
        self.p = dict(p)
        self.hour = 0.0
        for _ in range(people):
            Walker(self)

    def step(self) -> None:
        self.agents.shuffle_do("step")
        self.hour += 1.0

    def summary(self) -> dict[str, float]:
        walkers = [a for a in self.agents if isinstance(a, Walker)]
        out: dict[str, float] = {"distinct_locations": 0.0, "radius_of_gyration_km": 0.0,
                                 "top_location_share": 0.0}
        for w in walkers:
            pts = np.asarray(w.locations)
            weights = np.asarray(w.visits, dtype=float)
            centre = (pts * weights[:, None]).sum(axis=0) / weights.sum()
            rg = math.sqrt(float((weights * ((pts - centre) ** 2).sum(axis=1)).sum()
                                 / weights.sum()))
            out["distinct_locations"] += len(pts) / len(walkers)
            out["radius_of_gyration_km"] += rg / len(walkers)
            out["top_location_share"] += float(weights.max() / weights.sum()) / len(walkers)
        return out


def simulate(p: Mapping[str, float], seed: int, hours: int, sample_h: int,
             people: int = 1) -> list[dict[str, float]]:
    model = MobilityModel(p, seed, people)
    rows = [model.summary()]
    for h in range(1, hours + 1):
        model.step()
        if h % sample_h == 0:
            rows.append(model.summary())
    return rows


def to_km(lat_lon: Sequence[tuple[float, float]]) -> Array:
    """Equirectangular projection around the first point, in kilometres."""
    pts = np.asarray(lat_lon, dtype=float)
    lat0 = math.radians(pts[0, 0])
    x = np.radians(pts[:, 1] - pts[0, 1]) * math.cos(lat0) * EARTH_RADIUS_KM
    y = np.radians(pts[:, 0] - pts[0, 0]) * EARTH_RADIUS_KM
    return np.column_stack([x, y])


@dataclass(frozen=True)
class Fit:
    rho: float
    gamma: float
    alpha: float
    beta: float
    moves: int


def fit_trace(t_h: Array, xy_km: Array, *, tolerance_km: float = 0.1,
              min_jump_km: float = 0.1, min_wait_h: float = 1.0) -> Fit:
    """Maximum-likelihood parameters from stay points: times (h) and positions (km).

    Stay points within `tolerance_km` of an earlier one are the same location.
    """
    places: list[Array] = []
    sequence: list[int] = []
    for point in xy_km:
        for j, place in enumerate(places):
            if float(np.hypot(*(point - place))) <= tolerance_km:
                sequence.append(j)
                break
        else:
            places.append(point)
            sequence.append(len(places) - 1)
    seen: set[int] = {sequence[0]}
    new_flags: list[bool] = []
    sizes: list[int] = []
    jumps: list[float] = []
    for prev, cur in pairwise(sequence):
        sizes.append(len(seen))
        is_new = cur not in seen
        new_flags.append(is_new)
        if is_new:
            jumps.append(float(np.hypot(*(places[cur] - places[prev]))))
            seen.add(cur)
    s = np.asarray(sizes, dtype=float)
    new = np.asarray(new_flags)

    def nll(theta: Array) -> float:
        prob = np.clip(theta[0] * s ** -theta[1], 1e-9, 1 - 1e-9)
        return float(-(new * np.log(prob) + (~new) * np.log1p(-prob)).sum())

    best = minimize(nll, np.array([0.6, 0.2]), bounds=[(0.01, 1.0), (0.0, 2.0)],
                    method="L-BFGS-B")
    waits = np.diff(np.asarray(t_h, dtype=float))
    waits = waits[waits >= min_wait_h]
    jump = np.asarray([j for j in jumps if j >= min_jump_km])
    alpha = float(len(jump) / np.log(jump / min_jump_km).sum()) if len(jump) else math.nan
    beta = float(len(waits) / np.log(waits / min_wait_h).sum()) if len(waits) else math.nan
    return Fit(float(best.x[0]), float(best.x[1]), alpha, beta, len(new))
