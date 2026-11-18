"""Explainers for forecasters, state-space sequences and online baselines (design 04, 4.6.1).

`shap_window` is SHAP on windowed features: the window is cut into blocks of consecutive
steps per column, and Kernel SHAP attributes the forecast to the blocks. It stands in for
TimeSHAP (see `deploy/SPIKES.md`). `counterfactual_trajectory` shows the forecast under
a changed recent history. `occlusion_sequence` attributes a hidden Markov model's state
probability to single observations. `baseline_deviation` reads an online baseline.
"""

from __future__ import annotations

import warnings

import numpy as np

from ahdt.xai.subjects import OnlineSubject, SequenceSubject, WindowSubject
from ahdt.xai.types import Array, Result, driver, drivers_from
from atra import contracts as c

SHAP_SAMPLES = 80


def _blocks(history: Array, block: int) -> list[tuple[int, int]]:
    """(start, stop) of each block; the last block ends at the most recent step."""
    return [(max(stop - block, 0), stop) for stop in range(len(history), 0, -block)][::-1]


def _labels(s: WindowSubject, spans: list[tuple[int, int]]) -> list[str]:
    n = len(s.history)
    return [f"{col}[t-{n - a}..t-{n - b + 1}]" for col in s.columns for a, b in spans]


def shap_window(s: WindowSubject, samples: int = SHAP_SAMPLES) -> Result:
    """Kernel SHAP over (column, block) features; a switched-off block is replaced by the
    column's window mean."""
    import shap

    spans = _blocks(s.history, s.block)
    names = _labels(s, spans)
    nb = len(spans)
    fill = s.history.mean(axis=0)

    def build(mask: Array) -> list[Array]:
        out = []
        for m in mask:
            w = s.history.copy()
            for ci in range(len(s.columns)):
                for bi, (a, b) in enumerate(spans):
                    if m[ci * nb + bi] < 0.5:
                        w[a:b, ci] = fill[ci]
            out.append(w)
        return out

    def f(mask: Array) -> Array:
        return s.score(build(np.atleast_2d(mask)))

    k = len(names)
    explainer = shap.KernelExplainer(f, np.zeros((1, k)))
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = explainer.shap_values(np.ones((1, k)), nsamples=samples, silent=True)
    values = np.asarray(raw[-1] if isinstance(raw, list) else raw, dtype=float).reshape(-1)
    last = [float(s.history[b - 1, ci]) for ci in range(len(s.columns)) for _, b in spans]
    from importlib.metadata import version

    return Result(f"shap.window@{version('shap')}", "temporal_attribution",
                  drivers_from(names, last, values), output=s.output,
                  base=float(np.asarray(explainer.expected_value).reshape(-1)[-1]),
                  detail={"block": s.block, "target": s.columns[s.target],
                          "horizon": s.horizon, "fallback_for": "timeshap"})


def counterfactual_trajectory(s: WindowSubject, steps: int = 7, sd: float = 1.0) -> Result:
    """Forecast of the target column when its last `steps` values move by +/- `sd` standard
    deviations of the window."""
    base = s.forecast(s.history)[:, s.target]
    spread = float(s.history[:, s.target].std())
    found = []
    for sign in (-1.0, 1.0):
        w = s.history.copy()
        w[-steps:, s.target] += sign * sd * spread
        alt = s.forecast(w)[:, s.target]
        found.append(c.Counterfactual(
            changes={f"{s.columns[s.target]}_last_{steps}_steps": sign * sd * spread},
            outcome={"mean_forecast": float(alt.mean()),
                     "change": float(alt.mean() - base.mean())}))
    return Result("counterfactual.trajectory@own", "counterfactual", output=s.output,
                  counterfactuals=found,
                  detail={"forecast": [float(v) for v in base], "steps": steps})


def prototype_trajectory(s: WindowSubject, prototypes: list[Array] | None = None) -> Result:
    """The reference history closest to the window and the forecasts of both. Without
    prototypes the reference is the window's own column mean."""
    refs = prototypes or [np.tile(s.history.mean(axis=0), (len(s.history), 1))]
    dist = [float(np.linalg.norm(r - s.history)) for r in refs]
    best = refs[int(np.argmin(dist))]
    ours = s.forecast(s.history)[:, s.target]
    theirs = s.forecast(best)[:, s.target]
    gap = float(ours.mean() - theirs.mean())
    return Result("prototype.trajectory@own", "temporal_attribution",
                  [driver("forecast_vs_prototype", gap, gap)], output=s.output,
                  detail={"distance": min(dist), "forecast": [float(v) for v in ours],
                          "prototype_forecast": [float(v) for v in theirs]})


def occlusion_sequence(s: SequenceSubject, neutral: dict[str, float] | None = None) -> Result:
    """Change of the target state's probability when one observation (step, channel) is
    replaced by the channel's most frequent value (categorical) or mean (continuous)."""
    full = s.obs
    neutral = neutral or {ch: float(np.median(full[:, i])) for i, ch in enumerate(s.channels)}
    base = s.output
    names, values, contributions = [], [], []
    t_last = len(full)
    for t in range(t_last):
        for i, ch in enumerate(s.channels):
            alt = full.copy()
            alt[t, i] = neutral[ch]
            changed = float(s.posterior(alt)[s.states.index(s.target)])
            names.append(f"{ch}[t-{t_last - 1 - t}]")
            values.append(full[t, i])
            contributions.append(base - changed)
    return Result("occlusion.sequence@own", "temporal_attribution",
                  drivers_from(names, values, contributions), output=base,
                  detail={"target_state": s.target})


def baseline_deviation(s: OnlineSubject) -> Result:
    """Each field's distance from the person's own baseline, in standard deviations."""
    z = s.score(s.x)
    return Result("baseline.deviation@own", "attribution",
                  [driver(f, s.x[f], float(z[f])) for f in s.fields], output=s.output,
                  base=0.0, detail={"threshold_z": s.threshold, "flag": s.output > s.threshold})
