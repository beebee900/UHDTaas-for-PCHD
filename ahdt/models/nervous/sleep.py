"""Circadian rhythm and sleep (inventory item 3): the two-process model.

Process S (sleep pressure) rises towards the asymptote `mu` while awake and decays
towards zero while asleep. Sleep starts when S reaches the upper threshold and ends at
the lower threshold; both thresholds are modulated by the circadian process
C(t) = sin(2 pi (t - alpha) / period). When an observed sleep state is supplied, S
follows it instead of switching by threshold.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, ModelSpec, OdeModel, Params, Port
from atra import contracts as c
from atra.connectors import DTKind

STEP_H = 1.0 / 60.0


def circadian(t_h: float, p: Params) -> float:
    return math.sin(2 * math.pi * (t_h - p["alpha"]) / p["period"])


class SleepModel(OdeModel):
    spec = ModelSpec(
        model_id="ahdt.nervous.circadian_rhythm_and_sleep",
        twin=DTKind.NERVOUS, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Sleep pressure, circadian phase and predicted sleep timing",
        instances=("UBERON:0000955",),
        inputs=(Port("asleep", "1", "input:wearable"),
                Port("clock_h", "h", "input:clock")),
        outputs=(Port("sleep_pressure", "1"), Port("circadian_process", "1"),
                 Port("asleep", "1"), Port("upper_threshold", "1"),
                 Port("lower_threshold", "1"), Port("circadian_phase", "h")),
        explainers=("counterfactual.scenario",))
    params_stem = "sleep"
    state_names = ("S", "asleep")
    time_scale_s = 3600.0

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {"S": 0.5 * (p["H0_plus"] + p["H0_minus"]), "asleep": 0.0}

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        rate = -y[0] / p["chi_s"] if y[1] >= 0.5 else (p["mu"] - y[0]) / p["chi_w"]
        return [rate, 0.0]

    def integrate(self, p: Params, y0: Array, t_eval: Array, u: Any, *,
                  param_path: Any = None, impulses: Any = ()) -> Array:
        """Exact exponential steps of one minute with threshold switching."""
        out = np.empty((len(t_eval), 2))
        if len(t_eval) == 0:
            return out
        s, asleep = float(y0[0]), float(y0[1])
        t, j = 0.0, 0
        while j < len(t_eval) and t_eval[j] <= 0:
            out[j] = (s, asleep)
            j += 1
        while j < len(t_eval):
            step = min(STEP_H, float(t_eval[j]) - t)
            inputs = u(t)
            clock = t + float(inputs.get("clock_h", 0.0))
            if inputs.get("asleep") is not None:
                asleep = float(inputs["asleep"])
            else:
                ct = p["a"] * circadian(clock, p)
                if asleep < 0.5 and s >= p["H0_plus"] + ct:
                    asleep = 1.0
                elif asleep >= 0.5 and s <= p["H0_minus"] + ct:
                    asleep = 0.0
            if asleep >= 0.5:
                s = s * math.exp(-step / p["chi_s"])
            else:
                s = p["mu"] + (s - p["mu"]) * math.exp(-step / p["chi_w"])
            t += step
            while j < len(t_eval) and t_eval[j] <= t + 1e-9:
                out[j] = (s, asleep)
                j += 1
        return out

    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        clock = t + float(u.get("clock_h", 0.0))
        ct = circadian(clock, p)
        return {"sleep_pressure": float(y[0]), "circadian_process": ct,
                "asleep": float(y[1]), "upper_threshold": p["H0_plus"] + p["a"] * ct,
                "lower_threshold": p["H0_minus"] + p["a"] * ct,
                "circadian_phase": (clock - p["alpha"]) % p["period"]}

    def sleep_episodes(self, p: Params, days: float = 7.0,
                       clock_h: float = 0.0) -> list[tuple[float, float]]:
        """Free-running (onset, offset) clock times in hours over the last days of a run."""
        t = np.arange(0.0, days * 24.0, STEP_H)
        ys = self.integrate(p, np.array([0.5, 0.0]), t, lambda _t: {"clock_h": clock_h})
        flips = np.flatnonzero(np.diff(ys[:, 1]) != 0) + 1
        episodes, onset = [], None
        for i in flips:
            if ys[i, 1] >= 0.5:
                onset = t[i] + clock_h
            elif onset is not None:
                episodes.append((onset % 24.0, (t[i] + clock_h) % 24.0))
                onset = None
        return episodes

    def fit_schedule(self, onsets_h: Sequence[float], offsets_h: Sequence[float],
                     p: Params | None = None) -> dict[str, float]:
        """Phase and upper threshold that reproduce the observed sleep timing.

        The upper threshold sets the sleep duration; the phase only shifts the timing, so it
        follows from the midpoint once the threshold is chosen. `duration_error_h` reports
        how far the best threshold is from the observed duration.
        """
        base = {**(p or self.base_params()), "alpha": 0.0}
        on, off = _circ_mean(onsets_h), _circ_mean(offsets_h)
        duration = (off - on) % 24.0
        best: tuple[float, float, float] | None = None
        for step in range(50):
            threshold = 0.40 + 0.01 * step
            episodes = self.sleep_episodes({**base, "H0_plus": threshold}, days=5.0)[-2:]
            if not episodes:
                continue
            e_on, e_off = (float(x) for x in episodes[-1])
            err = abs((e_off - e_on) % 24.0 - duration)
            if best is None or err < best[0]:
                best = (err, threshold, (e_on + ((e_off - e_on) % 24.0) / 2) % 24.0)
        if best is None:
            raise ValueError("no parameter set produces consolidated sleep")
        fit_err, h_plus, mid = best
        alpha = (on + duration / 2 - mid) % base["period"]
        return {"alpha": float(alpha), "H0_plus": h_plus, "duration_error_h": fit_err}


def _circ_mean(hours: Sequence[float]) -> float:
    angles = np.asarray(hours) / 24.0 * 2 * np.pi
    return float(np.arctan2(np.sin(angles).mean(), np.cos(angles).mean()) / (2 * np.pi) * 24.0
                 % 24.0)


def _circ_diff(a: float, b: float) -> float:
    return (a - b + 12.0) % 24.0 - 12.0
