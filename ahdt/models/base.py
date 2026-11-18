"""Base classes of the AHDT Layer 4 models (design 03, 3.4; design 04, 4.5).

`AlgebraicModel` covers equations and scores evaluated at one instant. `OdeModel` covers
models with a state vector integrated in time. Both implement the `Layer4Model` protocol:

- `predict` evaluates the outputs for the current instance state and inputs.
- `simulate` integrates an `OdeModel` over a horizon under a scenario.
- `calibrate` personalises the calibratable parameters by maximum a posteriori fitting
  (Gaussian priors on the log parameters, Gaussian observation noise) and returns the
  updated instance record with posterior standard deviations.
"""

from __future__ import annotations

import abc
import asyncio
import math
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, ClassVar

import numpy as np
from scipy.integrate import solve_ivp
from scipy.optimize import least_squares

from ahdt.models.arrays import Array
from ahdt.models.params import ParamSet, load_params, params_path
from atra import contracts as c
from atra.connectors import DTKind
from atra.ids import new_output_id
from atra.kb import KnowledgeBase
from atra.provenance import record_hash
from atra.units import convert

type Inputs = Mapping[str, Any]
type Params = Mapping[str, float]
type Drive = Callable[[float], Mapping[str, Any]]
type ParamPath = Callable[[float, Params], Params]
type Impulse = tuple[float, Mapping[str, float]]

DEFAULT_OBS_CV = 0.05
DEFAULT_PRIOR_CV = 0.3


@dataclass(frozen=True)
class Port:
    """One model input or output. `from_` says where an input comes from (design 03, 3.4)."""

    name: str
    unit: str
    from_: str | None = None
    substance: str | None = None


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    twin: DTKind
    family: c.ModelFamily
    tier: c.Tier
    intended_use: str
    version: str = "1.0.0"
    inputs: tuple[Port, ...] = ()
    outputs: tuple[Port, ...] = ()
    instances: tuple[str, ...] = ()
    validity: Mapping[str, Any] = field(default_factory=dict)
    explainers: tuple[str, ...] = ()
    depends_on: tuple[tuple[str, str], ...] = ()
    obs_map: Mapping[str, str] = field(default_factory=dict)
    fidelity_note: str | None = None
    source: str | None = None

    @property
    def anatomy(self) -> str | None:
        return self.instances[0] if self.instances else None

    def output(self, name: str) -> Port:
        for port in self.outputs:
            if port.name == name:
                return port
        raise KeyError(f"{self.model_id} has no output {name}")

    def entry(self, params: ParamSet | None,
              validation: c.Validation | None = None) -> c.ModelRegistryEntry:
        source = self.source or (params.citation() if params else None)
        if not source:
            raise ValueError(f"{self.model_id} has no source")
        return c.ModelRegistryEntry(
            model_id=self.model_id, version=self.version, twin=self.twin, family=self.family,
            tier=self.tier, anatomy=self.anatomy,
            inputs=[c.ModelInput(name=p.name, unit=p.unit, **{"from": p.from_ or p.name})
                    for p in self.inputs],
            outputs=[c.ModelIO(name=p.name, unit=p.unit) for p in self.outputs],
            validity=dict(self.validity), validation=validation,
            intended_use=self.intended_use, explainers=list(self.explainers),
            depends_on=[c.ModelRef(model_id=m, version=v) for m, v in self.depends_on],
            source=source)


def hdt_of(record: c.InstanceRecord | None, inputs: Inputs) -> str:
    if "hdt_id" in inputs:
        return str(inputs["hdt_id"])
    if record is not None and record.instance_id.startswith("inst-hdt-"):
        return "-".join(record.instance_id.split("-")[1:3])
    return ""


def _plain(value: Any) -> float | str | list[float] | list[str]:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, list | tuple | np.ndarray):
        items = list(value)
        if all(isinstance(v, str) for v in items):
            return [str(v) for v in items]
        return [float(v) for v in items]
    return float(value)


def _numeric(values: Mapping[str, Any]) -> dict[str, float]:
    return {k: float(v) for k, v in values.items()
            if isinstance(v, int | float) and not isinstance(v, bool)}


class Layer4Base(abc.ABC):
    """Shared behaviour of every Layer 4 model."""

    spec: ModelSpec
    params_stem: ClassVar[str | None] = None

    def __init__(self, params: ParamSet | None = None, *,
                 kb: KnowledgeBase | None = None) -> None:
        if params is None and self.params_stem is not None:
            module_file = sys.modules[type(self).__module__].__file__
            assert module_file is not None
            params = load_params(params_path(module_file, self.params_stem))
        if params is not None and params.model_id != self.spec.model_id:
            raise ValueError(f"{params.model_id} parameters given to {self.spec.model_id}")
        self.paramset = params
        self.kb = kb

    @property
    def model_id(self) -> str:
        return self.spec.model_id

    @property
    def version(self) -> str:
        return self.spec.version

    @property
    def family(self) -> c.ModelFamily:
        return self.spec.family

    @property
    def tier(self) -> c.Tier:
        return self.spec.tier

    def base_params(self) -> dict[str, float]:
        return self.paramset.values if self.paramset else {}

    def parameters(self, record: c.InstanceRecord | None = None) -> dict[str, float]:
        p = self.base_params()
        if record is not None:
            p.update(_numeric(record.params))
        return p

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {}

    def impulses(self, scenario: c.Scenario | None, inputs: Inputs) -> list[Impulse]:
        """Instant state changes (model time, {state: increment}), such as a meal or a bolus."""
        return []

    @abc.abstractmethod
    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        """Output values for one instant."""

    def new_record(self, hdt_id: str, anatomy: str, owner: DTKind,
                   inputs: Inputs | None = None) -> c.InstanceRecord:
        from atra.ids import instance_id

        p = self.parameters()
        state = self.initial_state(p, inputs or {})
        state.update({k: v for k, v in self.evaluate(p, state, inputs or {}).items()
                      if k not in state})
        return c.InstanceRecord(instance_id=instance_id(hdt_id, anatomy), anatomy=anatomy,
                                model_id=self.model_id, version=self.version, owner_dt=owner,
                                params={}, state=state)

    def _output(self, record: c.InstanceRecord | None, inputs: Inputs,
                values: Mapping[str, Any]) -> c.ModelOutput:
        uncertainty: dict[str, c.Uncertainty] = {}
        if record is not None:
            for name, u in record.uncertainty.items():
                if name in values and isinstance(u, Mapping) and "std" in u:
                    uncertainty[name] = c.StdDev(std=float(u["std"]))
        ref = "inputs:" + record_hash({"inputs": dict(inputs),
                                       "state": record.state if record else {}})[:24]
        return c.ModelOutput(output_id=new_output_id(), model_id=self.model_id,
                             version=self.version, hdt_id=hdt_of(record, inputs),
                             values={k: _plain(v) for k, v in values.items() if v is not None},
                             uncertainty=uncertainty, inputs_ref=ref,
                             created_at=datetime.now(UTC))

    def series(self, p: Params, state: Mapping[str, Any], t_s: Array, u: Drive, *,
               param_path: ParamPath | None = None,
               impulses: Sequence[Impulse] = ()) -> dict[str, Array]:
        """Outputs at each time `t_s` (seconds) under the inputs `u(t_s)`."""
        rows = [self.evaluate(param_path(float(t), p) if param_path else p, state, u(float(t)))
                for t in t_s]
        names = [port.name for port in self.spec.outputs
                 if rows and isinstance(rows[0].get(port.name), int | float)]
        return {n: np.array([float(r.get(n, np.nan)) for r in rows]) for n in names}

    async def predict(self, inputs: Inputs, state: c.InstanceRecord | None) -> c.ModelOutput:
        p = self.parameters(state)
        current = dict(state.state) if state is not None else self.initial_state(p, inputs)
        values = await asyncio.to_thread(self.evaluate, p, current, inputs)
        return self._output(state, inputs, values)

    async def simulate(self, state: c.InstanceRecord, scenario: c.Scenario, horizon_s: float,
                       step_s: float) -> c.Trajectory:
        raise NotImplementedError(f"{self.model_id} is not a simulation model")

    async def calibrate(self, state: c.InstanceRecord, obs: Sequence[c.ObservationRecord], *,
                        inputs: Inputs | None = None) -> c.InstanceRecord:
        """Assimilate the latest observed value of every mapped output into the state."""
        latest = _latest_by_output(self.spec, obs)
        if not latest:
            return state
        new_state = dict(state.state)
        for name, (_, value) in latest.items():
            new_state[name] = value
        last = max(when for when, _ in latest.values())
        return state.model_copy(update={"state": new_state, "last_assimilated": last})


def _observed(spec: ModelSpec, o: c.ObservationRecord) -> tuple[str, float] | None:
    name = spec.obs_map.get(o.code.code)
    if name is None or not isinstance(o.value, int | float) or o.quality is c.Quality.REJECTED:
        return None
    port = spec.output(name)
    value = float(o.value)
    if o.unit != port.unit:
        value = convert(value, o.unit, port.unit, substance=port.substance)
    return name, value


def _latest_by_output(spec: ModelSpec, obs: Sequence[c.ObservationRecord]
                      ) -> dict[str, tuple[datetime, float]]:
    latest: dict[str, tuple[datetime, float]] = {}
    for o in obs:
        hit = _observed(spec, o)
        if hit is None:
            continue
        name, value = hit
        if name not in latest or o.effective_time >= latest[name][0]:
            latest[name] = (o.effective_time, value)
    return latest


class AlgebraicModel(Layer4Base):
    """Equations or scores evaluated at one instant.

    `simulate` is quasi-static: the outputs are evaluated at every step with the inputs of
    that time, from `drive`.
    """

    time_scale_s: ClassVar[float] = 1.0

    def drive(self, scenario: c.Scenario | None, inputs: Inputs) -> Drive:
        merged = dict(inputs)
        if scenario is not None:
            for block in (scenario.activity, scenario.diet, scenario.environment,
                          scenario.intervention):
                if block:
                    merged.update(block)
        return lambda t: merged

    async def simulate(self, state: c.InstanceRecord, scenario: c.Scenario, horizon_s: float,
                       step_s: float, *, inputs: Inputs | None = None,
                       fork_id: str | None = None) -> c.Trajectory:
        if step_s <= 0 or horizon_s < 0:
            raise ValueError("step_s must be positive and horizon_s non-negative")
        p = self.parameters(state)
        u = self.drive(scenario, dict(inputs or {}))
        t_s = np.arange(0.0, horizon_s + step_s / 2, step_s)
        series = await asyncio.to_thread(self.series, p, state.state, t_s, u)
        return trajectory(self, t_s, series, fork_id=fork_id)


class OdeModel(Layer4Base):
    """A state-space model `dy/dt = f(t, y, p, u)` with algebraic outputs.

    Model time runs in the model's own unit; `time_scale_s` gives seconds per unit.
    """

    state_names: tuple[str, ...]
    time_scale_s: ClassVar[float] = 1.0
    method: ClassVar[str] = "LSODA"
    max_step: ClassVar[float] = math.inf
    rtol: ClassVar[float] = 1e-6
    atol: ClassVar[float] = 1e-8

    @abc.abstractmethod
    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        """Time derivative of the state vector."""

    @abc.abstractmethod
    def observe(self, t: float, y: Array, p: Params,
                u: Mapping[str, Any]) -> dict[str, Any]:
        """Outputs at one time point."""

    def drive(self, scenario: c.Scenario | None, inputs: Inputs) -> Drive:
        """Inputs as a function of model time. The default holds them constant, with scenario
        overrides from its `activity`, `diet`, `environment` and `intervention` blocks."""
        merged = dict(inputs)
        if scenario is not None:
            for block in (scenario.activity, scenario.diet, scenario.environment,
                          scenario.intervention):
                if block:
                    merged.update(block)
        return lambda t: merged

    def events(self, t: Array, series: Mapping[str, Array],
               p: Params) -> list[c.TrajectoryEvent]:
        return []

    def vector(self, state: Mapping[str, Any], p: Params, inputs: Inputs) -> Array:
        initial = self.initial_state(p, inputs)
        return np.array([float(state.get(n, initial[n])) for n in self.state_names])

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        return self.observe(0.0, self.vector(state, p, inputs), p, inputs)

    def integrate(self, p: Params, y0: Array, t_eval: Array, u: Drive, *,
                  param_path: ParamPath | None = None,
                  impulses: Sequence[Impulse] = ()) -> Array:
        """State at each time in `t_eval` (model units), shape (len(t_eval), n_states).

        An impulse at time t is applied before the state at t is reported.
        """
        out = np.empty((len(t_eval), len(y0)))
        if len(t_eval) == 0:
            return out

        def f(t: float, y: Array) -> Sequence[float]:
            pt = param_path(t, p) if param_path is not None else p
            return self.rhs(t, y, pt, u(t))

        kicks = sorted(((t, d) for t, d in impulses if t <= t_eval[-1]), key=lambda k: k[0])
        y = np.array(y0, dtype=float)
        k = 0
        while k < len(kicks) and kicks[k][0] <= 0:
            self._kick(y, kicks[k][1])
            k += 1
        start, done = 0.0, 0
        while done < len(t_eval):
            stop = kicks[k][0] if k < len(kicks) else math.inf
            rest = t_eval[done:]
            seg = rest[rest < stop]
            end = stop if stop < math.inf else float(seg[-1])
            points = np.unique(np.concatenate([seg, [end]]))
            ys = self._segment(f, start, end, y, points)
            out[done:done + len(seg)] = ys[:len(seg)]
            done += len(seg)
            y, start = ys[-1].copy(), end
            if stop < math.inf:
                self._kick(y, kicks[k][1])
                k += 1
        return out

    def _kick(self, y: Array, delta: Mapping[str, float]) -> None:
        for name, value in delta.items():
            y[self.state_names.index(name)] += value

    def _segment(self, f: Callable[[float, Array], Sequence[float]], start: float,
                 end: float, y: Array, points: Array) -> Array:
        if end <= start:
            return np.tile(y, (len(points), 1))
        sol = solve_ivp(f, (start, end), y, method=self.method, t_eval=points, rtol=self.rtol,
                        atol=self.atol, max_step=self.max_step)
        if not sol.success:
            raise RuntimeError(f"{self.model_id}: integration failed: {sol.message}")
        return np.asarray(sol.y.T)

    def run(self, p: Params, y0: Array, t_eval: Array, u: Drive, *,
            param_path: ParamPath | None = None,
            impulses: Sequence[Impulse] = ()) -> tuple[Array, dict[str, Array]]:
        ys = self.integrate(p, y0, t_eval, u, param_path=param_path, impulses=impulses)
        rows = [self.observe(float(t), y, param_path(float(t), p) if param_path else p,
                             u(float(t)))
                for t, y in zip(t_eval, ys, strict=True)]
        names = [port.name for port in self.spec.outputs if rows and port.name in rows[0]]
        series = {n: np.array([float(r[n]) for r in rows]) for n in names}
        for i, n in enumerate(self.state_names):
            series.setdefault(n, ys[:, i])
        return ys, series

    def series(self, p: Params, state: Mapping[str, Any], t_s: Array, u: Drive, *,
               param_path: ParamPath | None = None,
               impulses: Sequence[Impulse] = ()) -> dict[str, Array]:
        scale = self.time_scale_s

        def path(t: float, q: Params) -> Params:
            assert param_path is not None
            return param_path(t * scale, q)

        _, out = self.run(p, self.vector(state, p, {}), t_s / scale,
                          lambda t: u(t * scale), param_path=path if param_path else None,
                          impulses=impulses)
        return out

    def final_state(self, ys: Array) -> dict[str, float]:
        return {n: float(v) for n, v in zip(self.state_names, ys[-1], strict=True)}

    async def simulate(self, state: c.InstanceRecord, scenario: c.Scenario, horizon_s: float,
                       step_s: float, *, inputs: Inputs | None = None,
                       param_path: ParamPath | None = None,
                       fork_id: str | None = None) -> c.Trajectory:
        if step_s <= 0 or horizon_s < 0:
            raise ValueError("step_s must be positive and horizon_s non-negative")
        p = self.parameters(state)
        ins = dict(inputs or {})
        y0 = self.vector(state.state, p, ins)
        t_s = np.arange(0.0, horizon_s + step_s / 2, step_s)
        t_model = t_s / self.time_scale_s
        u = self.drive(scenario, ins)
        _, series = await asyncio.to_thread(self.run, p, y0, t_model, u,
                                            param_path=param_path,
                                            impulses=self.impulses(scenario, ins))
        units = {port.name: port.unit for port in self.spec.outputs if port.name in series}
        return c.Trajectory(
            output_id=new_output_id(), model_id=self.model_id, version=self.version,
            t=[float(x) for x in t_s],
            series={k: [float(x) for x in v] for k, v in series.items() if k in units},
            units=units, events=self.events(t_s, series, p), fork_id=fork_id)

    async def calibrate(self, state: c.InstanceRecord,
                        obs: Sequence[c.ObservationRecord], *,
                        inputs: Inputs | None = None) -> c.InstanceRecord:
        points = [(o.effective_time, hit) for o in obs if (hit := _observed(self.spec, o))]
        names = self.paramset.calibratable() if self.paramset else []
        if not points:
            return state
        points.sort(key=lambda x: x[0])
        t0 = state.last_assimilated or points[0][0]
        rel = np.array([(when - t0).total_seconds() / self.time_scale_s for when, _ in points])
        if np.any(rel < 0):
            raise ValueError("observations older than the instance state")
        fit = await asyncio.to_thread(self._map_fit, state, names, points, rel, dict(inputs or {}))
        return fit.model_copy(update={"last_assimilated": points[-1][0]})

    def _map_fit(self, state: c.InstanceRecord, names: list[str],
                 points: list[tuple[datetime, tuple[str, float]]], rel: Array,
                 inputs: dict[str, Any]) -> c.InstanceRecord:
        assert self.paramset is not None or not names
        base = self.parameters(state)
        y0 = self.vector(state.state, base, inputs)
        u = self.drive(None, inputs)
        kicks = self.impulses(None, inputs)
        times = np.unique(rel)
        index = {t: i for i, t in enumerate(times)}
        observed = [(index[t], name, value) for t, (_, (name, value)) in zip(rel, points,
                                                                           strict=True)]
        prior = np.log([base[n] for n in names])
        prior_sd = np.array([math.sqrt(math.log1p((self.paramset.params[n].prior_cv  # type: ignore[union-attr]
                                                   or DEFAULT_PRIOR_CV) ** 2))
                             for n in names])

        def outputs_for(theta: Array) -> tuple[Array, dict[str, Array]]:
            p = dict(base)
            p.update({n: float(math.exp(v)) for n, v in zip(names, theta, strict=True)})
            return self.run(p, y0, times, u, impulses=kicks)

        def residuals(theta: Array) -> Array:
            _, series = outputs_for(theta)
            r = [(series[name][i] - value) / max(abs(value) * DEFAULT_OBS_CV, 1e-9)
                 for i, name, value in observed]
            return np.concatenate([np.array(r), (theta - prior) / prior_sd])

        if names:
            result = least_squares(residuals, prior, method="trf", x_scale="jac")
            theta = result.x
            try:
                cov = np.linalg.inv(result.jac.T @ result.jac)
                sd_log = np.sqrt(np.clip(np.diag(cov), 0.0, None))
            except np.linalg.LinAlgError:
                sd_log = prior_sd
        else:
            theta, sd_log = prior, np.zeros(0)
        ys, _ = outputs_for(theta)
        fitted = {n: float(math.exp(v)) for n, v in zip(names, theta, strict=True)}
        uncertainty = dict(state.uncertainty)
        uncertainty.update({n: {"std": fitted[n] * float(s)}
                            for n, s in zip(names, sd_log, strict=True)})
        params = dict(state.params)
        params.update(fitted)
        new_state = dict(state.state)
        new_state.update(self.final_state(ys))
        new_state.update({k: v for k, v in self.observe(
            float(times[-1]), ys[-1], {**base, **fitted}, u(float(times[-1]))).items()})
        return state.model_copy(update={"params": params, "state": new_state,
                                        "uncertainty": uncertainty})


def trajectory(model: Layer4Base, t_s: Array, series: Mapping[str, Array], *,
               fork_id: str | None = None,
               events: Sequence[c.TrajectoryEvent] = ()) -> c.Trajectory:
    units = {port.name: port.unit for port in model.spec.outputs if port.name in series}
    return c.Trajectory(output_id=new_output_id(), model_id=model.model_id,
                        version=model.version, t=[float(x) for x in t_s],
                        series={k: [float(x) for x in series[k]] for k in units},
                        units=units, events=list(events), fork_id=fork_id)
