"""Layer 6.2 model tools (design 04, 4.7.3): state, forecast, simulate, cosimulate, facet,
calibrate.

- `state` assimilates the latest observations into the twin's organ instances and reports
  the instances' state with a status taken from the field reference ranges.
- `forecast` projects the person's own series with a damped-trend forecaster.
- `simulate` and `cosimulate` run on forks of the needed instances. The live instances are
  never written, and the fork is released when the call ends.
- `calibrate` re-fits an instance's model to the person's observations and writes the result
  as the assimilation service.
"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import numpy as np
from pydantic import BaseModel

from ahdt.models.base import AlgebraicModel, Layer4Base, OdeModel
from ahdt.models.organs.store import ASSIMILATION, ForkHandle
from ahdt.registry import FacetDecl
from ahdt.services import forecasting
from ahdt.services.observations import ObservationReader, Reading
from ahdt.services.outputs import StoredOutput
from ahdt.services.runtime import ResolvedInputs, Runtime, worst
from atra import contracts as c
from atra.connectors import DTKind
from atra.ids import new_output_id
from atra.kb import KBError
from atra.service import Identity, Problem, ToolHandler, meta

SIMULATION_POINTS = 48
COSIMULATION_STEPS = 24
MIN_OBSERVATIONS = 2
STATUS_ORDER = ("normal", "watch", "alert")
COSIM_MODEL = "ahdt.whole_body.cosimulation"
COSIM_VERSION = "1.0.0"

type OutputHook = Callable[[StoredOutput, Mapping[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class Crossing:
    """A forecast that reaches a critical limit of the field."""

    field: str
    limit: float
    side: str
    at_h: float


def field_status(ref: Mapping[str, Any], value: float) -> str:
    """`alert` beyond the critical limits, `watch` beyond the warning limits."""
    for low, high, level in (("crit_low", "crit_high", "alert"),
                             ("warn_low", "warn_high", "watch")):
        lo, hi = ref.get(low), ref.get(high)
        if (lo is not None and value < lo) or (hi is not None and value > hi):
            return level
    return "normal"


class ModelService:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime
        self.on_output: OutputHook | None = None

    # ------------------------------------------------------------------ state

    def reference_range(self, ref: str | None) -> Mapping[str, Any] | None:
        if not ref:
            return None
        try:
            content: Mapping[str, Any] = self.rt.kb.resolve(ref)
        except KBError:
            return None
        return content

    def _status(self, kind: DTKind, reader: ObservationReader,
                readings: Mapping[str, Reading]) -> str:
        definition = self.rt.registry.get(kind)
        levels = []
        for f in definition.fields if definition else ():
            ref = self.reference_range(f.ref)
            reading = readings.get(reader.canonical(f.name))
            if reading is None or ref is None or not isinstance(reading.value, float):
                continue
            levels.append(field_status(ref, reading.value))
        return worst(levels)

    async def state(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        return await self.state_of(a.hdt_id, a.dt)

    async def state_of(self, hdt_id: str, kind: DTKind) -> dict[str, Any]:
        """The `ahdt.model.state` result for one twin of one person."""
        rt = self.rt
        await rt.assimilate(hdt_id, kind)
        reader = await rt.reader()
        readings = reader.latest(hdt_id, twin=kind)
        merged: dict[str, Any] = {}
        updated: list[datetime] = [r.effective_time for r in readings.values()]
        lead = rt.lead_model(kind)
        lead_record = None
        definition = rt.registry.get(kind)
        for anatomy in definition.owns_instances if definition else ():
            record = await rt.store.get(hdt_id, anatomy)
            if lead is not None and record.model_id == lead.model_id and lead_record is None:
                lead_record = record
            for key, value in record.state.items():
                merged.setdefault(key, value)
            if record.last_assimilated:
                updated.append(record.last_assimilated)
        for code, reading in readings.items():
            name = reader.field_name(code)
            if name is not None and reading.value is not None:
                merged[name] = reading.value
        status = self._status(kind, reader, readings)
        output_id = new_output_id()
        model_id, version = ((lead.model_id, lead.version) if lead is not None
                             else (f"ahdt.{kind.value}.observed_state", "1.0.0"))
        inputs = await rt.resolve(lead, hdt_id) if lead is not None else None
        stored = (await rt.outputs()).put(StoredOutput(
            output_id=output_id, model_id=model_id, version=version, hdt_id=hdt_id,
            kind="state" if lead is not None else "observed", twin=kind.value,
            values={k: v for k, v in merged.items() if isinstance(v, int | float | str)},
            inputs=inputs.values if inputs else {},
            state=lead_record.state if lead_record else {},
            params=lead_record.params if lead_record else {},
            sources=inputs.sources if inputs else {}),
            used=list(dict.fromkeys([*(inputs.used if inputs else []),
                                     *(r.record_id for r in readings.values())])))
        if self.on_output:
            await self.on_output(stored, {"status": status})
        return {"dt": kind.value, "state": merged, "status": status,
                "updated_at": (max(updated) if updated else datetime.now(UTC)).isoformat(),
                "output_id": output_id, "_meta": meta((model_id, version), output_id=output_id)}

    # --------------------------------------------------------------- forecast

    async def forecast(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        kind: DTKind = a.dt
        rt = self.rt
        reader = await rt.reader()
        definition = rt.registry.get(kind)
        field = next((f for f in definition.fields if f.name == a.variable), None) \
            if definition else None
        if field is None:
            raise Problem(422, "invalid-arguments",
                          f"{kind.value} has no field named {a.variable}")
        code = reader.canonical(a.variable)
        rows = [r for r in reader.read(a.hdt_id, [code], twin=kind)
                if isinstance(r.value, float)]
        if len(rows) < forecasting.MIN_POINTS:
            raise Problem(409, "insufficient-data",
                          f"{a.variable} has {len(rows)} readings; a forecast needs "
                          f"{forecasting.MIN_POINTS}")
        origin = rows[-1].effective_time
        hours = [(r.effective_time - rows[0].effective_time).total_seconds() / 3600
                 for r in rows]
        grid, step_h = forecasting.regular_grid(hours, [float(r.value) for r in rows])  # type: ignore[arg-type]
        fitted = forecasting.fit(grid)
        steps = forecasting.ahead(a.horizon_h, step_h)
        mean, half = forecasting.forecast(fitted, steps)
        t = [step_h * i for i in range(steps + 1)]
        now_value = float(grid[-1])
        mean_all = [now_value, *mean.tolist()]
        half_all = [0.0, *half.tolist()]
        keep = _thin_index(len(t), SIMULATION_POINTS + 1)
        out_id = new_output_id()
        model_id = f"ahdt.{kind.value}.damped_trend_forecaster"
        window = [{"t": h, "v": float(v)} for h, v in
                  zip(np.arange(len(grid)) * step_h, grid, strict=True)]
        stored = (await rt.outputs()).put(StoredOutput(
            output_id=out_id, model_id=model_id, version=forecasting.VERSION, hdt_id=a.hdt_id,
            kind="forecast", twin=kind.value,
            values={"variable": a.variable, "horizon_h": a.horizon_h, "step_h": step_h,
                    "steps": steps, "origin": origin.isoformat()},
            inputs={"variable": a.variable}, window=window), used=[r.record_id for r in rows])
        body = {"t": [t[i] for i in keep], "mean": [mean_all[i] for i in keep],
                "lower": [mean_all[i] - half_all[i] for i in keep],
                "upper": [mean_all[i] + half_all[i] for i in keep],
                "level": forecasting.LEVEL, "output_id": out_id,
                "_meta": meta((model_id, forecasting.VERSION), output_id=out_id)}
        if self.on_output:
            await self.on_output(stored, {"crossing": self._crossing(field.ref, field.name,
                                                                      body, a.horizon_h)})
        return body

    def _crossing(self, ref_id: str | None, name: str, body: Mapping[str, Any],
                  horizon_h: float) -> Crossing | None:
        ref = self.reference_range(ref_id)
        if ref is None:
            return None
        for t, mean in zip(body["t"][1:], body["mean"][1:], strict=True):
            if t > horizon_h + 1e-9:
                break
            for key, side in (("crit_high", "above"), ("crit_low", "below")):
                limit = ref.get(key)
                if limit is not None and ((side == "above" and mean > limit)
                                          or (side == "below" and mean < limit)):
                    return Crossing(name, float(limit), side, float(t))
        return None

    # ------------------------------------------------------------- simulation

    async def _fork(self, hdt_id: str, kinds: Sequence[DTKind]) -> ForkHandle:
        """A fork of the owned instances and facet sources of `kinds`."""
        rt = self.rt
        anatomies: list[str] = []
        for kind in kinds:
            definition = rt.registry.get(kind)
            if definition is None:
                continue
            anatomies += definition.owns_instances
            anatomies += [r.instance for r in definition.reads_facets]
            for model in rt.models_of(kind):
                anatomies += model.spec.instances
        anatomies = list(dict.fromkeys(anatomies))
        await rt.ensure(hdt_id, anatomies)
        return await rt.store.fork(hdt_id, anatomies)

    def _candidates(self, kind: DTKind, scenario: c.Scenario) -> list[Layer4Base]:
        models = [m for m in self.rt.models_of(kind) if m.spec.instances
                  and isinstance(m, OdeModel | AlgebraicModel)]
        acted: list[Layer4Base] = []
        rest: list[Layer4Base] = []
        for m in models:
            try:
                hit = bool(m.impulses(scenario, {}))
            except Exception:
                continue
            (acted if hit else rest).append(m)
        rest.sort(key=lambda m: not isinstance(m, OdeModel))
        return acted + rest

    async def _simulate_one(self, model: Layer4Base, fork: ForkHandle, hdt_id: str,
                            scenario: c.Scenario, horizon_s: float, step_s: float,
                            extra: Mapping[str, Any] | None = None
                            ) -> tuple[c.Trajectory, c.InstanceRecord, ResolvedInputs]:
        record = await fork.get(hdt_id, model.spec.instances[0])
        resolved = await self.rt.resolve(model, hdt_id, store=fork, supplied=extra)
        accepted = inspect.signature(model.simulate).parameters
        kwargs: dict[str, Any] = {}
        if "inputs" in accepted:
            kwargs["inputs"] = resolved.values
        if "fork_id" in accepted:
            kwargs["fork_id"] = fork.fork_id
        traj = await model.simulate(record, scenario, horizon_s, step_s, **kwargs)
        return traj, record, resolved

    async def simulate(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        rt = self.rt
        kinds = list(dict.fromkeys([a.dt, *a.scenario.dts]))
        fork = await self._fork(a.hdt_id, kinds)
        try:
            horizon_s = a.horizon_h * 3600.0
            step_s = horizon_s / SIMULATION_POINTS
            failures = []
            for model in self._candidates(a.dt, a.scenario):
                try:
                    traj, record, inputs = await self._simulate_one(
                        model, fork, a.hdt_id, a.scenario, horizon_s, step_s)
                except Exception as exc:
                    failures.append(f"{model.model_id}: {exc}")
                    continue
                final = {k: v[-1] for k, v in traj.series.items() if v}
                await fork.write(a.hdt_id, record.anatomy, writer=ASSIMILATION,
                                 state=final, params=None,
                                 expected_revision=record.revision)
                stored = (await rt.outputs()).put(StoredOutput(
                    output_id=traj.output_id, model_id=model.model_id, version=model.version,
                    hdt_id=a.hdt_id, kind="trajectory", twin=a.dt.value,
                    values={"horizon_s": horizon_s, "final": final}, inputs=inputs.values,
                    state=record.state, params=record.params, sources=inputs.sources))
                body = traj.model_copy(update={"fork_id": fork.fork_id}).model_dump(mode="json")
                body["_meta"] = meta((model.model_id, model.version), forked=True,
                                     fork_id=fork.fork_id, output_id=traj.output_id)
                if self.on_output:
                    await self.on_output(stored, {})
                return body
            detail = "; ".join(failures) or "no model of the twin has an instance"
            raise Problem(422, "unsupported-scenario",
                          f"no model of {a.dt.value} simulates this scenario ({detail})")
        finally:
            await rt.store.release(fork.fork_id)

    @staticmethod
    def _shifted(scenario: c.Scenario, elapsed_h: float) -> c.Scenario:
        """The scenario seen from `elapsed_h` hours into it: later doses keep their offsets."""
        if scenario.drug is None:
            return scenario
        later = [h - elapsed_h for h in scenario.drug.schedule_h if h >= elapsed_h]
        return scenario.model_copy(update={"drug": scenario.drug.model_copy(
            update={"schedule_h": later})})

    async def cosimulate(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        """Jacobi master over one simulating model per twin: every model advances one
        communication step from the outputs the others had at the previous step."""
        a: Any = args
        rt = self.rt
        fork = await self._fork(a.hdt_id, a.dts)
        try:
            horizon_s = a.horizon_h * 3600.0
            n_steps = max(1, min(COSIMULATION_STEPS, int(horizon_s // a.step_s) or 1))
            comm_s = horizon_s / n_steps
            members: dict[DTKind, Layer4Base] = {}
            for kind in a.dts:
                found = self._candidates(kind, a.scenario)
                if not found:
                    raise Problem(422, "unsupported-scenario",
                                  f"{kind.value} has no model that can be co-simulated")
                members[kind] = found[0]
            records = {k: await fork.get(a.hdt_id, m.spec.instances[0])
                       for k, m in members.items()}
            latest: dict[str, dict[str, Any]] = {}
            times = [0.0]
            series: dict[str, list[float]] = {}
            units: dict[str, str] = {}
            for kind, model in members.items():
                resolved = await rt.resolve(model, a.hdt_id, store=fork)
                start = model.evaluate(model.parameters(records[kind]), records[kind].state,
                                       resolved.values)
                latest[model.model_id] = start
                for port in model.spec.outputs:
                    if _numeric(start.get(port.name)):
                        series[f"{kind.value}.{port.name}"] = [float(start[port.name])]
                        units[f"{kind.value}.{port.name}"] = port.unit
            for k in range(n_steps):
                scenario = self._shifted(a.scenario, k * comm_s / 3600.0)
                snapshot = {mid: dict(v) for mid, v in latest.items()}
                for kind, model in members.items():
                    traj, _, _ = await self._simulate_one(
                        model, fork, a.hdt_id, scenario, comm_s, comm_s,
                        _coupled_inputs(model, snapshot))
                    end = {key: v[-1] for key, v in traj.series.items() if v}
                    records[kind] = records[kind].model_copy(
                        update={"state": {**records[kind].state, **end}})
                    latest[model.model_id] = end
                    for port in model.spec.outputs:
                        name = f"{kind.value}.{port.name}"
                        if name in series:
                            series[name].append(float(end.get(port.name, series[name][-1])))
                times.append((k + 1) * comm_s)
            out_id = new_output_id()
            traj_out = c.Trajectory(
                output_id=out_id, model_id=COSIM_MODEL, version=COSIM_VERSION, t=times,
                series=series, units=units, events=[], fork_id=fork.fork_id)
            stored = (await rt.outputs()).put(StoredOutput(
                output_id=out_id, model_id=COSIM_MODEL, version=COSIM_VERSION,
                hdt_id=a.hdt_id, kind="cosimulation", twin="whole_body",
                values={"members": {k.value: m.model_id for k, m in members.items()},
                        "communication_step_s": comm_s}))
            body = traj_out.model_dump(mode="json")
            body["_meta"] = meta(*((m.model_id, m.version) for m in members.values()),
                                 forked=True, fork_id=fork.fork_id, output_id=out_id)
            if self.on_output:
                await self.on_output(stored, {})
            return body
        finally:
            await rt.store.release(fork.fork_id)

    # ------------------------------------------------------------------ facet

    async def facet(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        decl: FacetDecl | None = self.rt.registry.facet(a.anatomy, a.facet)
        if decl is None:
            raise Problem(404, "not-found", f"no facet {a.facet} of {a.anatomy}")
        await self.rt.ensure(a.hdt_id, [a.anatomy])
        view = await self.rt.store.get_facet(a.hdt_id, a.anatomy, a.facet,
                                             consumer=decl.consumers[0])
        return view.model_dump(mode="json")

    # -------------------------------------------------------------- calibrate

    async def calibrate(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        model = self.rt.catalogue.get(a.model_id)
        if model is None or model.spec.twin is not a.dt:
            raise Problem(404, "not-found", f"{a.dt.value} has no model {a.model_id}")
        body = await self.calibrate_model(a.hdt_id, model)
        return {**body, "_meta": meta((model.model_id, model.version))}

    async def calibrate_model(self, hdt_id: str, model: Layer4Base) -> dict[str, Any]:
        """Re-fit one model's instance to the observations since its last assimilation."""
        rt = self.rt
        if not model.spec.instances:
            raise Problem(422, "invalid-arguments", f"{model.model_id} has no organ instance")
        anatomy = model.spec.instances[0]
        await rt.ensure(hdt_id, [anatomy])
        reader = await rt.reader()
        record = await rt.store.get(hdt_id, anatomy)
        readings = reader.read(hdt_id, list(model.spec.obs_map), start=record.last_assimilated)
        obs = [o for r in readings if (o := r.record(hdt_id)) is not None]
        if len(obs) < MIN_OBSERVATIONS:
            raise Problem(409, "insufficient-data",
                          f"{model.model_id} has {len(obs)} new observations; calibration "
                          f"needs {MIN_OBSERVATIONS}")
        before = _fit_error(model, record.state, obs)
        resolved = await rt.resolve(model, hdt_id)
        try:
            fitted = await model.calibrate(record, obs, inputs=resolved.values)
        except ValueError as exc:
            raise Problem(422, "calibration-failed", str(exc)) from exc
        after = _fit_error(model, fitted.state, obs)
        written = await rt.store.write(
            hdt_id, anatomy, writer=ASSIMILATION, state=fitted.state, params=fitted.params,
            expected_revision=record.revision, uncertainty=fitted.uncertainty)
        return {"instance_id": written.instance_id, "revision": written.revision,
                "fit_before": before, "fit_after": after}

    async def calibrate_all(self, hdt_id: str) -> list[dict[str, Any]]:
        """Calibrate every model that has new observations; the result of each, or why not."""
        done = []
        for model in self.rt.catalogue.values():
            if not model.spec.obs_map or not model.spec.instances:
                continue
            try:
                done.append({"model_id": model.model_id,
                             **await self.calibrate_model(hdt_id, model)})
            except Problem as exc:
                done.append({"model_id": model.model_id, "skipped": exc.detail})
        return done

    async def infer(self, model_id: str, version: str, hdt_id: str,
                    inputs: Mapping[str, Any]) -> c.ModelOutput:
        """One run of a catalogue model on the person's instance (the gRPC `Infer`)."""
        rt = self.rt
        model = rt.catalogue.get(model_id)
        if model is None or (version and version != model.version):
            raise LookupError(f"no model {model_id} {version}".strip())
        record = None
        if model.spec.instances:
            await rt.ensure(hdt_id, model.spec.instances[:1])
            record = await rt.store.get(hdt_id, model.spec.instances[0])
        resolved = await rt.resolve(model, hdt_id, supplied=inputs)
        out = await model.predict(resolved.values, record)
        out = out.model_copy(update={"hdt_id": hdt_id})
        (await rt.outputs()).put(StoredOutput(
            output_id=out.output_id, model_id=out.model_id, version=out.version, hdt_id=hdt_id,
            kind="state", twin=model.spec.twin.value, values=out.values,
            inputs=resolved.values, state=record.state if record else {},
            params=record.params if record else {}, sources=resolved.sources),
            used=resolved.used)
        return out

    def handlers(self) -> dict[str, ToolHandler]:
        return {"ahdt.model.state": self.state, "ahdt.model.forecast": self.forecast,
                "ahdt.model.simulate": self.simulate, "ahdt.model.cosimulate": self.cosimulate,
                "ahdt.model.facet": self.facet, "ahdt.model.calibrate": self.calibrate}


def _numeric(value: Any) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _thin_index(n: int, limit: int) -> list[int]:
    if n <= limit:
        return list(range(n))
    step = (n - 1) / (limit - 1)
    return sorted({round(i * step) for i in range(limit)})


def _coupled_inputs(model: Layer4Base, outputs: Mapping[str, Mapping[str, Any]]
                    ) -> dict[str, Any]:
    """Inputs of `model` that name another model's output as their source."""
    from ahdt.models.coupling import parse

    found: dict[str, Any] = {}
    for port in model.spec.inputs:
        source = parse(port)
        if source is None or source.kind != "model":
            continue
        value = outputs.get(source.target, {}).get(source.item or port.name)
        if value is not None:
            found[port.name] = value
    return found


def _fit_error(model: Layer4Base, state: Mapping[str, Any],
               obs: Sequence[c.ObservationRecord]) -> float:
    """Mean relative error of the state's outputs against the latest observation of each."""
    latest: dict[str, tuple[datetime, float]] = {}
    for o in obs:
        name = model.spec.obs_map.get(o.code.code)
        if name is None or not isinstance(o.value, int | float):
            continue
        if name not in latest or o.effective_time >= latest[name][0]:
            latest[name] = (o.effective_time, float(o.value))
    errors = [abs(float(state[n]) - v) / max(abs(v), 1e-9) for n, (_, v) in latest.items()
              if isinstance(state.get(n), int | float)]
    return float(np.mean(errors)) if errors else 0.0

