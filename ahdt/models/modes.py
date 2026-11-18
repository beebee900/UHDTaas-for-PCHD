"""Truth mode and twin mode (design 08, WP14a step 6).

- Truth mode generates a synthetic person's physiology for WP02: each calibratable
  parameter is drawn around its published value with the parameter's prior spread, from a
  seed fixed by the person and the model, and the model runs under the person's disease
  drivers. The result is reproducible for the same seed.
- Twin mode personalises an instance from observations: the model calibrates the
  instance, and the result is written to the store as the assimilation service.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import numpy as np

from ahdt.models.base import DEFAULT_PRIOR_CV, Layer4Base, trajectory
from ahdt.models.drivers import Driver, apply_inputs, apply_params
from ahdt.models.organs.store import ASSIMILATION, InstanceStore
from atra import contracts as c


def person_seed(hdt_id: str, model_id: str, salt: int = 0) -> int:
    digest = hashlib.sha256(f"{hdt_id}|{model_id}|{salt}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


def personalise(model: Layer4Base, seed: int) -> dict[str, float]:
    """Individual values of the calibratable parameters, log-normal around the published
    value with the parameter's prior coefficient of variation."""
    if model.paramset is None:
        return {}
    rng = np.random.default_rng(seed)
    out = {}
    for name in model.paramset.calibratable():
        param = model.paramset.params[name]
        sigma = math.sqrt(math.log1p((param.prior_cv or DEFAULT_PRIOR_CV) ** 2))
        value = param.value * float(np.exp(rng.normal(0.0, sigma)))
        if param.bounds is not None:
            value = min(max(value, param.bounds[0]), param.bounds[1])
        out[name] = value
    return out


@dataclass(frozen=True)
class TruthRun:
    hdt_id: str
    params: dict[str, float]
    trajectory: c.Trajectory


async def run_truth(model: Layer4Base, *, hdt_id: str, horizon_s: float, step_s: float,
                    inputs: Mapping[str, Any] | None = None, drivers: Sequence[Driver] = (),
                    salt: int = 0, vary: bool = True) -> TruthRun:
    """The person's true trajectory of one model under their disease drivers."""
    individual = personalise(model, person_seed(hdt_id, model.model_id, salt)) if vary else {}
    p = {**model.parameters(), **individual}
    base = dict(inputs or {})
    model_id = model.model_id

    def u(t: float) -> Mapping[str, Any]:
        return apply_inputs(drivers, model_id, t, base)

    def param_path(t: float, q: Mapping[str, float]) -> Mapping[str, float]:
        return apply_params(drivers, model_id, t, q)

    start = u(0.0)
    state = model.initial_state(p, start)
    t_s = np.arange(0.0, horizon_s + step_s / 2, step_s)
    impulses = model.impulses(None, start)
    series = await asyncio.to_thread(model.series, p, state, t_s, u, param_path=param_path,
                                     impulses=impulses)
    return TruthRun(hdt_id, individual, trajectory(model, t_s, series))


async def assimilate(store: InstanceStore, model: Layer4Base, hdt_id: str, anatomy: str,
                     obs: Sequence[c.ObservationRecord],
                     inputs: Mapping[str, Any] | None = None) -> c.InstanceRecord:
    """Calibrate an instance to observations and write it as the assimilation service."""
    record = await store.get(hdt_id, anatomy)
    fitted = await model.calibrate(record, obs, inputs=inputs)
    return await store.write(hdt_id, anatomy, writer=ASSIMILATION, state=fitted.state,
                             params=fitted.params, expected_revision=record.revision,
                             uncertainty=fitted.uncertainty)
