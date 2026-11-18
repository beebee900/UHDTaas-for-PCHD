"""Explainers for simulation and physics models (design 04, 4.6.1, simulation/physics).

SALib (Sobol and Morris) ranks the parameters and inputs that move an output. chaospy
turns the same ranges into a polynomial-chaos uncertainty band. `local_sensitivity` and
`scenario_counterfactual` are the cheap on-request forms. `posterior_summary` reports a
calibrated model's parameter uncertainty.

Every parameter and numeric input varies over +/- `RANGE` of its value. The ranges
express how far a calibrated value may sit from the person's true value; they are a
reporting choice, not clinical data.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable, Mapping
from importlib.metadata import version
from typing import Any

import numpy as np

from ahdt.models.base import OdeModel
from ahdt.xai.subjects import MechanisticSubject
from ahdt.xai.types import Array, Result, driver
from atra import contracts as c

RANGE = 0.2
MAX_FACTORS = 6
SOBOL_BASE = 8
MORRIS_TRAJECTORIES = 6
PCE_ORDER = 2
BAND_LEVEL = 0.9


def factors(s: MechanisticSubject) -> dict[str, float]:
    """The values that vary: calibratable parameters (all parameters when none are
    marked), then numeric inputs, at most `MAX_FACTORS` in all."""
    params = s.model.paramset
    names = list(params.calibratable()) if params is not None else []
    if not names:
        names = list(s.params)
    chosen = {n: float(s.params[n]) for n in names if n in s.params and s.params[n] != 0}
    for key, value in s.inputs.items():
        if isinstance(value, int | float) and not isinstance(value, bool) and value != 0:
            chosen[f"input:{key}"] = float(value)
    return dict(list(chosen.items())[:MAX_FACTORS])


def response(s: MechanisticSubject) -> Callable[[Mapping[str, float]], float]:
    """The output as a function of overrides to the varied values."""
    m = s.model

    def f(theta: Mapping[str, float]) -> float:
        p = dict(s.params)
        u = dict(s.inputs)
        for key, value in theta.items():
            if key.startswith("input:"):
                u[key.removeprefix("input:")] = value
            else:
                p[key] = value
        if isinstance(m, OdeModel) and s.horizon_s > 0:
            y0 = m.vector(s.state, p, u)
            t = np.array([0.0, s.horizon_s / m.time_scale_s])
            _, series = m.run(p, y0, t, m.drive(None, u), impulses=m.impulses(None, u))
            return float(series[s.output_name][-1])
        if s.horizon_s > 0 and hasattr(m, "run"):
            series = m.run(p, u, np.array([0.0, s.horizon_s]))
            return float(series[s.output_name][-1])
        return float(m.evaluate(p, s.state, u)[s.output_name])

    return f


def _bounds(base: Mapping[str, float]) -> list[list[float]]:
    return [[v * (1 - RANGE), v * (1 + RANGE)] for v in base.values()]


def _slopes(f: Callable[[Mapping[str, float]], float], base: Mapping[str, float]
            ) -> dict[str, float]:
    out = {}
    for name, value in base.items():
        lo = f({**base, name: value * (1 - RANGE)})
        hi = f({**base, name: value * (1 + RANGE)})
        out[name] = (hi - lo) / (2 * RANGE * value) if value else 0.0
    return out


def _ranked(names: list[str], base: Mapping[str, float], scores: Array, signs: Mapping[str, float]
            ) -> list[c.Driver]:
    return [driver(n, base[n], float(np.copysign(sc, signs.get(n, 1.0) or 1.0)))
            for n, sc in zip(names, scores, strict=True)]


def sobol(s: MechanisticSubject, base_samples: int = SOBOL_BASE) -> Result:
    """Sobol total-order indices (SALib), signed by the local slope."""
    from SALib.analyze import sobol as analyse
    from SALib.sample import sobol as sample

    base = factors(s)
    f = response(s)
    names = list(base)
    problem = {"num_vars": len(names), "names": names, "bounds": _bounds(base)}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        grid = sample.sample(problem, base_samples, calc_second_order=False, seed=7)
        y = np.array([f(dict(zip(names, row, strict=True))) for row in grid])
        if np.ptp(y) == 0:
            st: Array = np.zeros(len(names))
            s1: Array = np.zeros(len(names))
            conf: Array = np.zeros(len(names))
        else:
            res = analyse.analyze(problem, y, calc_second_order=False, print_to_console=False,
                                  seed=7)
            st, s1, conf = (np.nan_to_num(np.asarray(res[k]), nan=0.0)
                            for k in ("ST", "S1", "ST_conf"))
    slopes = _slopes(f, base)
    return Result(f"salib.sobol@{version('SALib')}", "sensitivity",
                  _ranked(names, base, st, slopes), output=f(base),
                  detail={"output": s.output_name,
                          "first_order": dict(zip(names, map(float, s1), strict=True)),
                          "total_conf": dict(zip(names, map(float, conf), strict=True)),
                          "evaluations": len(y), "range": RANGE})


def morris(s: MechanisticSubject, trajectories: int = MORRIS_TRAJECTORIES) -> Result:
    """Morris elementary effects (SALib): mu* ranks the factors, sigma shows interaction."""
    from SALib.analyze import morris as analyse
    from SALib.sample import morris as sample

    base = factors(s)
    f = response(s)
    names = list(base)
    problem = {"num_vars": len(names), "names": names, "bounds": _bounds(base)}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        grid = sample.sample(problem, trajectories, num_levels=4, seed=7)
        y = np.array([f(dict(zip(names, row, strict=True))) for row in grid])
        if np.ptp(y) == 0:
            mu_star = np.zeros(len(names))
            sigma = np.zeros(len(names))
        else:
            res = analyse.analyze(problem, grid, y, num_levels=4, print_to_console=False,
                                  seed=7)
            mu_star = np.nan_to_num(np.asarray(res["mu_star"]), nan=0.0)
            sigma = np.nan_to_num(np.asarray(res["sigma"]), nan=0.0)
    slopes = _slopes(f, base)
    return Result(f"salib.morris@{version('SALib')}", "sensitivity",
                  _ranked(names, base, mu_star, slopes), output=f(base),
                  detail={"output": s.output_name,
                          "sigma": dict(zip(names, map(float, sigma), strict=True)),
                          "evaluations": len(y), "range": RANGE})


def polynomial_chaos(s: MechanisticSubject, order: int = PCE_ORDER) -> Result:
    """A polynomial-chaos surrogate (chaospy) over the varied values: the mean, the
    standard deviation and the central 90 % band of the output."""
    import chaospy

    base = factors(s)
    f = response(s)
    names = list(base)
    dist = chaospy.J(*[chaospy.Uniform(lo, hi) for lo, hi in _bounds(base)])
    expansion = chaospy.generate_expansion(order, dist)
    n = max(2 * len(expansion), 8)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        nodes = dist.sample(n, rule="sobol")
        evals = np.array([f(dict(zip(names, nodes[:, i], strict=True))) for i in range(n)])
        approx = chaospy.fit_regression(expansion, nodes, evals)
        draw = approx(*dist.sample(2000, rule="random", seed=11))
        mean, std = float(chaospy.E(approx, dist)), float(chaospy.Std(approx, dist))
    lo, hi = np.quantile(draw, [(1 - BAND_LEVEL) / 2, 1 - (1 - BAND_LEVEL) / 2])
    slopes = _slopes(f, base)
    contribution = [float(slopes[k] * base[k] * RANGE) for k in names]
    return Result(f"chaospy.pce@{version('chaospy')}", "sensitivity",
                  [driver(k, base[k], v) for k, v in zip(names, contribution, strict=True)],
                  output=f(base),
                  uncertainty={"kind": "polynomial_chaos", "mean": mean, "std": std,
                               "lower": float(lo), "upper": float(hi), "level": BAND_LEVEL,
                               "output": s.output_name},
                  detail={"order": order, "evaluations": int(n)})


def local_sensitivity(s: MechanisticSubject) -> Result:
    """Change of the output for a +/- `RANGE` change of each value, one at a time."""
    base = factors(s)
    f = response(s)
    centre = f(base)
    drivers = []
    spans = {}
    for name, value in base.items():
        lo = f({**base, name: value * (1 - RANGE)})
        hi = f({**base, name: value * (1 + RANGE)})
        drivers.append(driver(name, value, hi - lo))
        spans[name] = {"low": lo, "high": hi}
    return Result("sensitivity.local@own", "sensitivity", drivers, output=centre,
                  detail={"output": s.output_name, "range": RANGE, "response": spans})


def scenario_counterfactual(s: MechanisticSubject,
                            changes: Mapping[str, float] | None = None) -> Result:
    """The output under named changes to inputs or parameters. Without `changes`, each
    varied value is halved and raised by half in turn."""
    base = factors(s)
    f = response(s)
    centre = f(base)
    trials: list[dict[str, float]] = ([dict(changes)] if changes else
                                      [{k: v * m} for k, v in base.items() for m in (0.5, 1.5)])
    found = []
    for trial in trials:
        out = f({**base, **{k: float(v) for k, v in trial.items()}})
        found.append(c.Counterfactual(changes={k.removeprefix("input:"): float(v)
                                               for k, v in trial.items()},
                                      outcome={s.output_name: out, "change": out - centre}))
    return Result("counterfactual.scenario@own", "counterfactual", output=centre,
                  counterfactuals=found, detail={"output": s.output_name})


def posterior_summary(s: MechanisticSubject, trace: Any | None = None) -> Result:
    """Parameter uncertainty of a calibrated model. With a PyMC trace (arviz InferenceData)
    this is the posterior summary; otherwise it is the Laplace standard deviations stored
    on the organ instance, as a normal 90 % interval."""
    summary: dict[str, dict[str, float]] = {}
    if trace is not None:
        import arviz

        table = arviz.summary(trace, hdi_prob=BAND_LEVEL)
        for name, row in table.iterrows():
            summary[str(name)] = {"mean": float(row["mean"]), "sd": float(row["sd"]),
                                  "lower": float(row.iloc[2]), "upper": float(row.iloc[3])}
        source = f"arviz@{version('arviz')}"
    else:
        z = 1.6448536269514722
        for name, sd in s.posterior_std.items():
            mean = float(s.params.get(name, 0.0))
            summary[name] = {"mean": mean, "sd": float(sd), "lower": mean - z * sd,
                             "upper": mean + z * sd}
        source = "laplace"
    drivers = [driver(k, v["mean"], v["sd"]) for k, v in summary.items()]
    return Result(f"posterior.summary@{source}", "sensitivity", drivers,
                  uncertainty={"kind": "posterior", "parameters": summary,
                               "level": BAND_LEVEL})
