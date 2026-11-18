"""T3 reference-state models (design 01, rule R3; design 04, 4.5.3).

A reference-state model is a state vector with reference ranges. It has no published
mechanism, so it moves only through two things:

- observations, which set a variable to the observed value;
- inter-twin couplings, which shift a variable's target in proportion to how far a
  coupled input sits from its own reference value.

Between observations each variable relaxes towards its target with the time constant
declared for it, unless it is a held variable, which changes only when observed. Ranges,
normal values and coupling gains are knowledge-base entries (rule R5). A variable whose
kb normal value is not yet sourced has no target: it holds its last observed value and
reports the status `unknown` until it is observed.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import yaml
from pydantic import BaseModel, ConfigDict, Field

from ahdt.models.arrays import Array
from ahdt.models.base import Inputs, Layer4Base, ModelSpec, OdeModel, Params, Port
from ahdt.models.params import Param, ParamSet, Source
from atra import contracts as c
from atra.config import get_settings
from atra.connectors import DTKind
from atra.kb import KBError, KnowledgeBase

ASSUMED_DYNAMICS = Source(
    id="atra-t3-dynamics",
    citation="ATRA design 01 rule R3: T3 reference-state relaxation time constants are "
             "modelling assumptions, not published values")


@lru_cache(maxsize=1)
def default_kb() -> KnowledgeBase:
    return KnowledgeBase(get_settings().kb_dir)


@lru_cache(maxsize=1)
def _reference_adult() -> Mapping[str, Any]:
    values: Mapping[str, Any] = default_kb().resolve("population.reference_adult")
    return values


def person_value(u: Mapping[str, Any], name: str) -> Any:
    """The person's input value, or the reference adult's value when it is missing."""
    value = u.get(name)
    if value is not None:
        return value
    try:
        return _reference_adult()[name]
    except KeyError:
        raise KeyError(f"no value for '{name}' and no reference value in the kb") from None


class Coupling(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    input: str
    from_: str = Field(alias="from")
    unit: str
    target: str
    gain: str = Field(description="kb entry: change of the target per unit of input deviation")
    reference: str = Field(description="kb entry: the input value with no effect")


class Variable(BaseModel):
    model_config = ConfigDict(extra="forbid")

    unit: str
    ref: str = Field(description="kb reference-range entry")
    tau_h: float = Field(gt=0, description="relaxation time constant (assumption)")
    justification: str
    hold: bool = Field(False, description="changes only through observations")


class ReferenceStateDef(BaseModel):
    model_config = ConfigDict(extra="forbid")

    model_id: str
    twin: DTKind
    intended_use: str
    instances: list[str] = Field(default_factory=list)
    variables: dict[str, Variable]
    couplings: list[Coupling] = Field(default_factory=list)
    obs_map: dict[str, str] = Field(default_factory=dict)


def _number(value: Any) -> float | None:
    return float(value) if isinstance(value, int | float) and not isinstance(value, bool) else None


class ReferenceStateModel(OdeModel):
    """One T3 inventory item, built from its definition."""

    time_scale_s = 3600.0
    method = "RK45"

    def __init__(self, definition: ReferenceStateDef, kb: KnowledgeBase | None = None) -> None:
        self.definition = definition
        self.state_names = tuple(definition.variables)
        outputs = [Port(name, v.unit) for name, v in definition.variables.items()]
        outputs += [Port(f"{name}_status", "{status}") for name in definition.variables]
        self.spec = ModelSpec(
            model_id=definition.model_id, twin=definition.twin, family=c.ModelFamily.SEMANTIC,
            tier=c.Tier.T3, intended_use=definition.intended_use,
            inputs=tuple({cp.input: Port(cp.input, cp.unit, cp.from_)
                          for cp in definition.couplings}.values()),
            outputs=tuple(outputs), instances=tuple(definition.instances),
            obs_map=definition.obs_map,
            source="Reference state over kb reference ranges: " + ", ".join(
                sorted({v.ref for v in definition.variables.values()})))
        super().__init__(ParamSet(
            model_id=definition.model_id, sources=[ASSUMED_DYNAMICS],
            params={f"tau_{name}": Param(value=v.tau_h, unit="h", source=ASSUMED_DYNAMICS.id,
                                         assumption=True, justification=v.justification)
                    for name, v in definition.variables.items()}), kb=kb or default_kb())

    def _range(self, name: str) -> Mapping[str, Any]:
        try:
            content = (self.kb or default_kb()).entry(
                self.definition.variables[name].ref).content()
        except KBError:
            return {}
        return content

    def normal(self, name: str) -> float | None:
        r = self._range(name)
        if (value := _number(r.get("normal"))) is not None:
            return value
        low, high = _number(r.get("ref_low")), _number(r.get("ref_high"))
        if low is not None and high is not None:
            return (low + high) / 2
        return None

    def _kb_number(self, entry_id: str) -> float | None:
        try:
            return _number((self.kb or default_kb()).resolve(entry_id))
        except KBError:
            return None

    def target(self, name: str, u: Mapping[str, Any], current: float) -> float:
        base = self.normal(name)
        if base is None or self.definition.variables[name].hold:
            return current
        shift = 0.0
        for cp in self.definition.couplings:
            if cp.target != name:
                continue
            value = _number(u.get(cp.input))
            gain, ref = self._kb_number(cp.gain), self._kb_number(cp.reference)
            if value is not None and gain is not None and ref is not None:
                shift += gain * (value - ref)
        return base + shift

    def status(self, name: str, value: float | None) -> str:
        if value is None or math.isnan(value):
            return "unknown"
        r = self._range(name)
        bands = [("crit", "critical"), ("warn", "warning"), ("ref", "abnormal")]
        for prefix, label in bands:
            low, high = _number(r.get(f"{prefix}_low")), _number(r.get(f"{prefix}_high"))
            if (low is not None and value < low) or (high is not None and value > high):
                return label
        if all(_number(r.get(f"{p}_{s}")) is None for p, _ in bands for s in ("low", "high")):
            return "unknown"
        return "normal"

    def initial_state(self, p: Params, inputs: Inputs) -> dict[str, Any]:
        return {name: self.normal(name) for name in self.definition.variables}

    def vector(self, state: Mapping[str, Any], p: Params, inputs: Inputs) -> Array:
        initial = self.initial_state(p, inputs)
        values = [state.get(n, initial[n]) for n in self.state_names]
        return np.array([math.nan if v is None else float(v) for v in values])

    def rhs(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> Sequence[float]:
        out = []
        for name, value in zip(self.state_names, y, strict=True):
            if math.isnan(value):
                out.append(0.0)
                continue
            out.append((self.target(name, u, value) - value) / p[f"tau_{name}"])
        return out

    def integrate(self, p: Params, y0: Array, t_eval: Array, u: Any, *,
                  param_path: Any = None, impulses: Any = ()) -> Array:
        known = ~np.isnan(y0)
        filled = np.where(known, y0, 0.0)
        ys = super().integrate(p, filled, t_eval, u, param_path=param_path, impulses=impulses)
        ys[:, ~known] = math.nan
        return ys

    def observe(self, t: float, y: Array, p: Params, u: Mapping[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for name, value in zip(self.state_names, y, strict=True):
            v = None if math.isnan(value) else float(value)
            if v is not None:
                out[name] = v
            out[f"{name}_status"] = self.status(name, v)
        return out

    def run(self, p: Params, y0: Array, t_eval: Array, u: Any, *,
            param_path: Any = None, impulses: Any = ()) -> tuple[Array, dict[str, Array]]:
        ys = self.integrate(p, y0, t_eval, u, param_path=param_path, impulses=impulses)
        return ys, {n: ys[:, i] for i, n in enumerate(self.state_names)}

    async def calibrate(self, state: c.InstanceRecord, obs: Sequence[c.ObservationRecord], *,
                        inputs: Inputs | None = None) -> c.InstanceRecord:
        updated = await Layer4Base.calibrate(self, state, obs, inputs=inputs)
        statuses = {f"{n}_status": self.status(n, _number(updated.state.get(n)))
                    for n in self.definition.variables}
        return updated.model_copy(update={"state": {**updated.state, **statuses}})


def load_definitions(path: Path) -> list[ReferenceStateDef]:
    with path.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or []
    return [ReferenceStateDef.model_validate(d) for d in data]
