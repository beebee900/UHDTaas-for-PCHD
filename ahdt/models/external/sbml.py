"""SBML models from BioModels run with libRoadRunner (design 04, 4.5.3; design 01, 1.3).

`SbmlModel` loads a pinned BioModels file (`sources.lock.yaml`), sets the model inputs and
parameters, integrates it and reads the outputs. The instance state holds the values of the
SBML variables named in `variables`. The simulator is created once per process.
"""

from __future__ import annotations

import abc
import asyncio
import threading
from collections.abc import Mapping
from typing import Any, ClassVar

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.base import Layer4Base, Params, trajectory
from ahdt.models.external import backends, baselines, sources
from atra import contracts as c

_RUNNERS: dict[str, Any] = {}
_LOCK = threading.RLock()


def runner(source_id: str) -> Any:
    """The RoadRunner instance of a pinned SBML file, created on first use."""
    backends.require(backends.roadrunner())
    with _LOCK:
        if source_id not in _RUNNERS:
            import roadrunner

            rr = roadrunner.RoadRunner(str(sources.fetch(source_id)))
            # Amounts that decay to zero stall the default 1e-12 tolerance in the denormal range.
            rr.integrator.absolute_tolerance = 1e-9
            _RUNNERS[source_id] = rr
        return _RUNNERS[source_id]


class SbmlModel(Layer4Base, abc.ABC):
    """A Layer 4 model backed by one SBML file."""

    source_id: ClassVar[str]
    variables: ClassVar[tuple[str, ...]]
    """SBML ids (species or rate-rule parameters) that make up the instance state."""
    sbml_params: ClassVar[Mapping[str, str]] = {}
    """Parameter name in the parameter file to SBML id; unlisted names are not SBML values."""
    sbml_inputs: ClassVar[Mapping[str, str]] = {}
    """Input port name to SBML id."""
    time_scale_s: ClassVar[float] = 86400.0
    settle: ClassVar[float] = 0.0
    """Model time to integrate from the SBML start values to reach the reference state."""
    steady: ClassVar[bool] = False
    """Solve for a steady state instead of integrating for `settle`."""

    @abc.abstractmethod
    def read(self, rr: Any) -> dict[str, Any]:
        """Outputs at the current simulator state."""

    def prepare(self, rr: Any, p: Params, inputs: Mapping[str, Any]) -> None:
        """Reset the simulator and apply the parameters and inputs."""
        rr.resetAll()
        for name, sid in self.sbml_params.items():
            if name in p:
                rr[sid] = p[name]
        for name, sid in self.sbml_inputs.items():
            if name in inputs:
                rr[sid] = float(inputs[name])

    def selections(self) -> list[str]:
        return [f"[{v}]" if self.is_species(v) else v for v in self.variables]

    def is_species(self, sid: str) -> bool:
        return sid in runner(self.source_id).model.getFloatingSpeciesIds()

    def apply_state(self, rr: Any, state: Mapping[str, Any]) -> None:
        for sid in self.variables:
            if sid in state:
                rr[sid] = float(state[sid])

    def current_state(self, rr: Any) -> dict[str, float]:
        return {v: float(rr[s]) for v, s in zip(self.variables, self.selections(), strict=True)}

    def initial_state(self, p: Params, inputs: Mapping[str, Any]) -> dict[str, Any]:
        cached = baselines.lookup(self.model_id, p, inputs)
        if cached is not None:
            return dict(cached["state"])
        return self.reference_state(p, inputs)

    def reference_state(self, p: Params, inputs: Mapping[str, Any]) -> dict[str, Any]:
        with _LOCK:
            rr = runner(self.source_id)
            self.prepare(rr, p, inputs)
            if self.steady:
                rr.steadyState()
            elif self.settle > 0:
                rr.simulate(0.0, self.settle, 2)
            return self.current_state(rr)

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Mapping[str, Any]
                 ) -> dict[str, Any]:
        cached = baselines.lookup(self.model_id, p, inputs)
        if cached is not None and all(state.get(k) == v for k, v in cached["state"].items()):
            return dict(cached["outputs"])
        with _LOCK:
            rr = runner(self.source_id)
            self.prepare(rr, p, inputs)
            self.apply_state(rr, state or self.initial_state(p, inputs))
            return self.read(rr)

    def baseline(self) -> baselines.Entry:
        """Run the backend for the default parameters and inputs."""
        p = self.parameters()
        state = self.reference_state(p, {})
        outputs = self.evaluate(p, state, {})
        return {"fingerprint": baselines.fingerprint(p, {}), "state": state,
                "outputs": outputs, "backend": f"libroadrunner {backends.roadrunner().version}"}

    def run(self, p: Params, state: Mapping[str, Any], inputs: Mapping[str, Any],
            t_model: Array) -> tuple[Array, dict[str, Array]]:
        """Output series at the model times `t_model` and the final state values."""
        columns: dict[str, list[float]] = {}
        with _LOCK:
            rr = runner(self.source_id)
            self.prepare(rr, p, inputs)
            self.apply_state(rr, state or self.initial_state(p, inputs))
            now = 0.0
            for t in t_model:
                if t > now:
                    now = float(rr.oneStep(now, float(t) - now))
                for name, value in self.read(rr).items():
                    if isinstance(value, int | float):
                        columns.setdefault(name, []).append(float(value))
            final = np.array([float(rr[s]) for s in self.selections()])
        return final, {k: np.array(v) for k, v in columns.items()}

    def drive_inputs(self, scenario: c.Scenario | None,
                     inputs: Mapping[str, Any]) -> dict[str, Any]:
        merged = dict(inputs)
        if scenario is not None:
            for block in (scenario.activity, scenario.diet, scenario.environment,
                          scenario.intervention):
                if block:
                    merged.update(block)
        return merged

    def events(self, t_model: Array, series: Mapping[str, Array]) -> list[c.TrajectoryEvent]:
        return []

    async def simulate(self, state: c.InstanceRecord, scenario: c.Scenario, horizon_s: float,
                       step_s: float, *, inputs: Mapping[str, Any] | None = None,
                       fork_id: str | None = None) -> c.Trajectory:
        if step_s <= 0 or horizon_s < 0:
            raise ValueError("step_s must be positive and horizon_s non-negative")
        p = self.parameters(state)
        ins = self.drive_inputs(scenario, inputs or {})
        t_s = np.arange(0.0, horizon_s + step_s / 2, step_s)
        series = await asyncio.to_thread(self.series_of, p, state.state, ins, t_s)
        t_model = t_s / self.time_scale_s
        return trajectory(self, t_s, series, fork_id=fork_id,
                          events=self.events(t_model, series))

    def series_of(self, p: Params, state: Mapping[str, Any], inputs: Mapping[str, Any],
                  t_s: Array) -> dict[str, Array]:
        _, series = self.run(p, state, inputs, t_s / self.time_scale_s)
        return series
