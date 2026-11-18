"""Layer 4 wrappers of the Mesa agent-based models (design 04, 4.5.3; design 08, WP14c step 5).

Both models are stochastic. The instance state holds aggregate quantities; each run builds
the agents from them and draws from a seed derived from the state, so a run is repeatable.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

import numpy as np

from ahdt.models.arrays import Array
from ahdt.models.base import Layer4Base, ModelSpec, Params, Port, trajectory
from ahdt.models.external import backends
from atra import contracts as c
from atra.connectors import DTKind

# mesa is in the full profile only, so the ABM modules load when a model runs.
if TYPE_CHECKING:
    from ahdt.models.external import immune_abm

DAY_S = 86400.0
HOUR_S = 3600.0


def seed_of(state: Mapping[str, Any], inputs: Mapping[str, Any]) -> int:
    blob = json.dumps([sorted(state.items()), sorted(inputs.items())], default=str)
    return int.from_bytes(hashlib.sha256(blob.encode()).digest()[:4], "big")


class ImmuneResponseModel(Layer4Base):
    spec = ModelSpec(
        model_id="ahdt.immune_lymphatic.t_cell_b_cell_and_macrophage",
        twin=DTKind.IMMUNE_LYMPHATIC, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Adaptive immune response to an antigen: T cell, B cell and macrophage counts",
        inputs=(Port("antigen_load", "1", "input:scenario"),),
        outputs=(Port("naive_t_cells", "{cells}"), Port("effector_t_cells", "{cells}"),
                 Port("memory_t_cells", "{cells}"), Port("naive_b_cells", "{cells}"),
                 Port("plasma_cells", "{cells}"), Port("active_macrophages", "{cells}"),
                 Port("antibody", "1"), Port("antigen", "1")),
        explainers=("sensitivity.local",),
        fidelity_note="Qualitative agent-based model on a lymph node section. Cell counts are "
                      "those of the model population, not of the whole body. Rate parameters "
                      "are assumptions listed on the card.")
    params_stem = "immune_abm"
    time_scale_s = DAY_S

    def initial_state(self, p: Params, inputs: Mapping[str, Any]) -> dict[str, Any]:
        return {"naive_t_cells": p["naive_t"], "effector_t_cells": 0.0, "memory_t_cells": 0.0,
                "naive_b_cells": p["naive_b"], "plasma_cells": 0.0,
                "active_macrophages": 0.0, "antibody": 0.0, "antigen": 0.0}

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Mapping[str, Any]
                 ) -> dict[str, Any]:
        base = self.initial_state(p, inputs)
        base.update({k: float(v) for k, v in state.items() if k in base})
        return base

    def run_days(self, p: Params, state: Mapping[str, Any], inputs: Mapping[str, Any],
                 days: float, sample_days: float) -> list[immune_abm.Counts]:
        backends.require(backends.mesa())
        from ahdt.models.external import immune_abm

        have = self.evaluate(p, state, inputs)
        antigen = float(inputs.get("antigen_load", have["antigen"]))
        initial = {"naive_t": have["naive_t_cells"], "memory_t": have["memory_t_cells"],
                   "naive_b": have["naive_b_cells"], "plasma": have["plasma_cells"],
                   "antibody": have["antibody"]}
        every = max(1, round(sample_days * immune_abm.TICKS_PER_DAY))
        return immune_abm.run(p, seed_of(state, inputs), antigen, days, every, initial)

    @staticmethod
    def as_outputs(row: immune_abm.Counts) -> dict[str, float]:
        return {"naive_t_cells": row.naive_t, "effector_t_cells": row.effector_t,
                "memory_t_cells": row.memory_t, "naive_b_cells": row.naive_b,
                "plasma_cells": row.plasma, "active_macrophages": row.macrophage_active,
                "antibody": row.antibody, "antigen": row.antigen}

    async def simulate(self, state: c.InstanceRecord, scenario: c.Scenario, horizon_s: float,
                       step_s: float, *, inputs: Mapping[str, Any] | None = None,
                       fork_id: str | None = None) -> c.Trajectory:
        if step_s <= 0 or horizon_s < 0:
            raise ValueError("step_s must be positive and horizon_s non-negative")
        ins = dict(inputs or {})
        for block in (scenario.environment, scenario.intervention):
            if block:
                ins.update(block)
        p = self.parameters(state)
        rows = await asyncio.to_thread(self.run_days, p, state.state, ins,
                                       horizon_s / DAY_S, step_s / DAY_S)
        series: dict[str, Array] = {}
        converted = [self.as_outputs(r) for r in rows]
        for name in converted[0]:
            series[name] = np.array([r[name] for r in converted])
        t_s = np.arange(len(rows)) * step_s
        events = []
        eff = series["effector_t_cells"]
        if eff.max() > 0:
            events.append(c.TrajectoryEvent(t=float(t_s[int(eff.argmax())]),
                                            kind="effector_peak",
                                            detail={"effector_t_cells": float(eff.max())}))
        return trajectory(self, t_s, series, fork_id=fork_id, events=events)


class MobilityModel(Layer4Base):
    spec = ModelSpec(
        model_id="ahdt.social.mobility",
        twin=DTKind.SOCIAL, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Places a person visits and how far they range, from their GPS stay points",
        inputs=(Port("rho", "1", "input:calibration"), Port("gamma", "1", "input:calibration")),
        outputs=(Port("distinct_locations", "{locations}"),
                 Port("radius_of_gyration_km", "km"), Port("top_location_share", "1"),
                 Port("new_location_probability", "1")),
        explainers=("sensitivity.local",),
        fidelity_note="Exploration and preferential return model; trace calibration uses stay "
                      "points, not raw GPS fixes.")
    params_stem = "mobility"
    time_scale_s = HOUR_S

    def initial_state(self, p: Params, inputs: Mapping[str, Any]) -> dict[str, Any]:
        return {"distinct_locations": 1.0, "radius_of_gyration_km": 0.0,
                "top_location_share": 1.0}

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Mapping[str, Any]
                 ) -> dict[str, Any]:
        out = self.initial_state(p, inputs)
        out.update({k: float(v) for k, v in state.items() if k in out})
        rho = float(inputs.get("rho", p["rho"]))
        gamma = float(inputs.get("gamma", p["gamma"]))
        out["new_location_probability"] = min(1.0, rho * out["distinct_locations"] ** -gamma)
        return out

    async def simulate(self, state: c.InstanceRecord, scenario: c.Scenario, horizon_s: float,
                       step_s: float, *, inputs: Mapping[str, Any] | None = None,
                       fork_id: str | None = None) -> c.Trajectory:
        if step_s <= 0 or horizon_s < 0:
            raise ValueError("step_s must be positive and horizon_s non-negative")
        backends.require(backends.mesa())
        from ahdt.models.external import mobility_abm

        p = dict(self.parameters(state))
        ins = dict(inputs or {})
        for key in ("rho", "gamma"):
            if key in ins:
                p[key] = float(ins[key])
        hours = int(horizon_s // HOUR_S)
        sample = max(1, round(step_s / HOUR_S))
        rows = await asyncio.to_thread(mobility_abm.simulate, p, seed_of(state.state, ins),
                                       hours, sample)
        t_s = np.arange(len(rows)) * sample * HOUR_S
        series = {name: np.array([r[name] for r in rows]) for name in rows[0]}
        series["new_location_probability"] = np.minimum(
            1.0, p["rho"] * series["distinct_locations"] ** -p["gamma"])
        return trajectory(self, t_s, series, fork_id=fork_id)

    def calibrate_trace(self, state: c.InstanceRecord, t_h: Array, xy_km: Array
                        ) -> c.InstanceRecord:
        """Fit rho, gamma, alpha and beta to a stay-point trace and store them as parameters."""
        from ahdt.models.external import mobility_abm

        fit = mobility_abm.fit_trace(t_h, xy_km)
        params = dict(state.params)
        params.update({"rho": fit.rho, "gamma": fit.gamma})
        if np.isfinite(fit.alpha):
            params["alpha"] = fit.alpha
        if np.isfinite(fit.beta):
            params["beta"] = fit.beta
        return state.model_copy(update={"params": params})
