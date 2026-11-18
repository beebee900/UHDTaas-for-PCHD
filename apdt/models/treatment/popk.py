"""Population pharmacokinetics with PyMC (design 05, 5.5.2).

A one-compartment model with first-order oral absorption and log-normal between-person
variability. The typical values come from `kb/popk/<drug>.yaml`, which cites the published
population model. An individual's clearance and volume are estimated from measured
concentrations by sampling the posterior of the random effects. A drug without a `popk.*`
entry has no model here.

A `popk.*` entry holds: `drug`, `typical` (`cl_l_h`, `v_l`, `ka_per_h`, `f`), `omega`
(log-scale standard deviations of `cl` and `v`), `sigma_prop` (proportional error), `weight`
(`reference_kg`, `exponent_cl`, `exponent_v`) and a `provenance` block.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray

from apdt.models.context import kb


def popk_entry(drug: str) -> Mapping[str, Any] | None:
    entry_id = f"popk.{drug.lower().replace(' ', '_')}"
    return kb().entry(entry_id).content() if entry_id in kb() else None


def concentration(t: NDArray[np.float64], dose_mg: float, cl: float, v: float, ka: float,
                  f: float) -> NDArray[np.float64]:
    """Plasma concentration (mg/L) after one oral dose, one compartment."""
    ke = cl / v
    if abs(ka - ke) < 1e-9:
        ka = ke * (1.0 + 1e-6)
    out: NDArray[np.float64] = f * dose_mg * ka / (v * (ka - ke)) * (np.exp(-ke * t)
                                                                      - np.exp(-ka * t))
    return out


@dataclass(frozen=True)
class IndividualEstimate:
    drug: str
    cl_l_h: float
    v_l: float
    cl_interval: tuple[float, float]
    v_interval: tuple[float, float]
    auc_mg_h_l: float
    typical_cl: float
    typical_v: float
    draws: int


def individual_pk(entry: Mapping[str, Any], dose_mg: float, weight_kg: float,
                  observations: Sequence[tuple[float, float]], *, draws: int = 300,
                  tune: int = 300, seed: int = 0) -> IndividualEstimate:
    """Posterior of one person's clearance and volume given `(hours, mg/L)` observations."""
    import pymc as pm

    typ, omega, w = entry["typical"], entry["omega"], entry["weight"]
    scale = weight_kg / float(w["reference_kg"])
    cl_t = float(typ["cl_l_h"]) * scale ** float(w["exponent_cl"])
    v_t = float(typ["v_l"]) * scale ** float(w["exponent_v"])
    ka, f = float(typ["ka_per_h"]), float(typ.get("f", 1.0))
    t = np.asarray([o[0] for o in observations], dtype=float)
    y = np.asarray([o[1] for o in observations], dtype=float)
    with pm.Model():
        eta_cl = pm.Normal("eta_cl", 0.0, float(omega["cl"]))
        eta_v = pm.Normal("eta_v", 0.0, float(omega["v"]))
        cl = pm.Deterministic("cl", cl_t * pm.math.exp(eta_cl))
        v = pm.Deterministic("v", v_t * pm.math.exp(eta_v))
        ke = cl / v
        pred = f * dose_mg * ka / (v * (ka - ke)) * (pm.math.exp(-ke * t) - pm.math.exp(-ka * t))
        pm.LogNormal("obs", mu=pm.math.log(pred), sigma=float(entry["sigma_prop"]),
                     observed=y)
        trace = pm.sample(draws=draws, tune=tune, chains=1, cores=1, random_seed=seed,
                          progressbar=False, compute_convergence_checks=False)
    cl_s = trace.posterior["cl"].to_numpy().ravel()
    v_s = trace.posterior["v"].to_numpy().ravel()
    auc = float(np.mean(f * dose_mg / cl_s))
    return IndividualEstimate(
        str(entry["drug"]), float(np.median(cl_s)), float(np.median(v_s)),
        (float(np.quantile(cl_s, 0.05)), float(np.quantile(cl_s, 0.95))),
        (float(np.quantile(v_s, 0.05)), float(np.quantile(v_s, 0.95))), auc, cl_t, v_t,
        len(cl_s))
