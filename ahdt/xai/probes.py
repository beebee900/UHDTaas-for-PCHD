"""Subjects for the catalogue models (T2 simulation and rule models, T3 reference states).

A mechanistic model is explained at an operating point: its parameters, a state and the
inputs it needs. `PROBES` names the inputs, the output of interest and the simulated
horizon for models that need more than the defaults; every other T2 model is explained at
its initial state, over `DEFAULT_HORIZON_S` for an ODE model, on its first numeric output.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from ahdt.models.base import Layer4Base, OdeModel
from ahdt.models.reference import ReferenceStateModel
from ahdt.xai.subjects import MechanisticSubject, ReferenceSubject, RuleSubject
from atra import contracts as c

DEFAULT_HORIZON_S = 3600.0


@dataclass(frozen=True)
class Probe:
    inputs: Mapping[str, Any] = field(default_factory=dict)
    output: str | None = None
    horizon_s: float | None = None


PROBES: Mapping[str, Probe] = {
    "ahdt.cardiovascular.baroreflex_regulation": Probe(horizon_s=20.0),
    "ahdt.nervous.neuron_and_circuit": Probe({"stimulus": 10.0}, horizon_s=0.02),
    "ahdt.sensory.sensory_decline": Probe({"age": 70.0}),
    "ahdt.integumentary.heat_stress": Probe({"air_temperature": 35.0,
                                             "relative_humidity": 60.0}),
    "ahdt.whole_body.life_course_and_ageing": Probe({"age": 67.0}),
    "ahdt.whole_body.maternal_foetal": Probe({"hc": 30.0, "ac": 30.0, "fl": 6.5,
                                              "gestation_weeks": 30.0}, output="efw"),
    "ahdt.immune_lymphatic.infection_response": Probe({"merozoite_release": 0.02},
                                                       output="parasitaemia",
                                                       horizon_s=4 * 86400.0),
    "ahdt.whole_body.early_warning": Probe({
        "respiration_rate": 24, "spo2": 95, "systolic_bp": 105, "pulse": 112,
        "temperature": 38.6, "consciousness": "alert"}),
    "ahdt.whole_body.pharmacogenomics": Probe({
        "diplotypes": {"CYP2D6": "*1/*4", "CYP2C19": "*1/*17"}, "drugs": ["codeine"]}),
}


def mechanistic_subject(model: Layer4Base, record: c.InstanceRecord | None = None, *,
                        inputs: Mapping[str, Any] | None = None) -> MechanisticSubject:
    """`model` at the operating point of `record` (or its initial state), explained on the
    probe's output."""
    probe = PROBES.get(model.model_id, Probe())
    u = {**probe.inputs, **(inputs or {})}
    p = model.parameters(record)
    state = dict(record.state) if record is not None else model.initial_state(p, u)
    if hasattr(model, "run") and not isinstance(model, OdeModel):
        horizon = probe.horizon_s or 0.0
    else:
        horizon = probe.horizon_s if probe.horizon_s is not None else (
            DEFAULT_HORIZON_S if isinstance(model, OdeModel) else 0.0)
    out = probe.output
    if out is None:
        values = model.evaluate(p, state, u)
        out = next((k for k, v in values.items()
                    if isinstance(v, int | float) and not isinstance(v, bool)), None)
    if out is None:
        out = next(port.name for port in model.spec.outputs)
    std = {k: float(v["std"]) for k, v in (record.uncertainty if record else {}).items()
           if isinstance(v, Mapping) and "std" in v}
    return MechanisticSubject(model, u, out, horizon, p, state, std)


def rule_subject(model: Layer4Base, inputs: Mapping[str, Any] | None = None) -> RuleSubject:
    probe = PROBES.get(model.model_id, Probe())
    return RuleSubject(model, {**probe.inputs, **(inputs or {})})


def reference_subject(model: ReferenceStateModel, record: c.InstanceRecord | None = None,
                      inputs: Mapping[str, Any] | None = None) -> ReferenceSubject:
    p = model.parameters(record)
    state = dict(record.state) if record is not None else model.initial_state(p, {})
    return ReferenceSubject(model, state, dict(inputs or {}))
