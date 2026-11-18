"""Disease drivers (design 08, WP14a step 4).

A driver is a course of disease that changes the inputs or parameters of one or more
models over time from its onset. Truth mode applies drivers to generate a synthetic
person's physiology; scenario runs apply them to ask what a course of disease would do.

Every magnitude (a rate of progression, a depth of injury, a treatment effect) is an
argument. Scenario authors take these values from knowledge-base entries or from the
synthetic population design, so no clinical number is fixed here (rule R5).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

DAY_S = 86400.0
YEAR_S = 365.25 * DAY_S
WEEK_S = 7 * DAY_S

type Profile = Callable[[float], float]


@dataclass(frozen=True)
class Effect:
    """How a driver acts on one model, as a function of time since onset in seconds.

    `input` sets an input value; `scale_param` multiplies a parameter.
    """

    model_id: str
    target: str
    kind: Literal["input", "scale_param"]
    profile: Profile


@dataclass(frozen=True)
class Driver:
    name: str
    onset_s: float
    effects: tuple[Effect, ...]
    fixed_inputs: Mapping[str, Mapping[str, object]] = field(default_factory=dict)

    def for_model(self, model_id: str) -> list[Effect]:
        return [e for e in self.effects if e.model_id == model_id]


def apply_inputs(drivers: Sequence[Driver], model_id: str, t_s: float,
                 base: Mapping[str, object]) -> dict[str, object]:
    """Inputs of a model at time t with every active driver applied."""
    out = dict(base)
    for d in drivers:
        out.update(d.fixed_inputs.get(model_id, {}))
        if t_s < d.onset_s:
            continue
        for e in d.for_model(model_id):
            if e.kind == "input":
                out[e.target] = e.profile(t_s - d.onset_s)
    return out


def apply_params(drivers: Sequence[Driver], model_id: str, t_s: float,
                 p: Mapping[str, float]) -> dict[str, float]:
    out = dict(p)
    for d in drivers:
        if t_s < d.onset_s:
            continue
        for e in d.for_model(model_id):
            if e.kind == "scale_param":
                out[e.target] = out[e.target] * e.profile(t_s - d.onset_s)
    return out


def constant(value: float) -> Profile:
    return lambda _t: value


INFECTION = "ahdt.immune_lymphatic.infection_response"
INFLAMMATION = "ahdt.immune_lymphatic.inflammation"
ERYTHRO = "ahdt.haematological.bone_marrow_and_erythrocytes"
KIDNEY = "ahdt.renal_urinary.kidney_and_renal_function"
HEART = "ahdt.cardiovascular.heart_chambers_and_valves"
GLUCOSE = "ahdt.endocrine.glucose_insulin_and_metabolic_regulation"
MATERNAL = "ahdt.whole_body.maternal_foetal"
PLACENTA = "ahdt.reproductive.placenta"


def malaria(onset_s: float, merozoite_release: float, *, treatment_after_d: float | None = None,
            antimalarial_kill: float = 0.0) -> Driver:
    """Within-host P. falciparum infection, treated after `treatment_after_d` days."""
    inputs: dict[str, object] = {"merozoite_release": merozoite_release}
    if treatment_after_d is not None:
        inputs.update({"antimalarial_kill": antimalarial_kill,
                       "antimalarial_start_d": treatment_after_d})
    return Driver("malaria", onset_s, (), {INFECTION: inputs})


def bacterial_infection(onset_s: float, inoculum: float, *,
                        treatment_after_h: float | None = None,
                        antimicrobial_kill: float = 0.0) -> Driver:
    """A bacterial inoculation driving the inflammatory response."""
    inputs: dict[str, object] = {"inoculations": [{"t_s": onset_s, "amount": inoculum}]}
    effects: tuple[Effect, ...] = ()
    if treatment_after_h is not None:
        start = treatment_after_h * 3600.0

        def kill(t: float) -> float:
            return antimicrobial_kill if t >= start else 0.0

        effects = (Effect(INFLAMMATION, "antimicrobial_kill", "input", kill),)
    return Driver("bacterial_infection", onset_s, effects, {INFLAMMATION: inputs})


def tuberculosis(onset_s: float, *, treatment_after_d: float | None = None) -> Driver:
    inputs: dict[str, object] = {"tb_active": True}
    if treatment_after_d is not None:
        inputs["tb_treatment_start_d"] = treatment_after_d
    return Driver("tuberculosis", onset_s, (), {INFECTION: inputs})


def hiv(onset_s: float, *, art_after_d: float | None = None, art_efficacy: float = 0.0
        ) -> Driver:
    inputs: dict[str, object] = {"hiv": True}
    if art_after_d is not None:
        inputs.update({"art_efficacy": art_efficacy, "art_start_d": art_after_d})
    return Driver("hiv", onset_s, (), {INFECTION: inputs})


def haemolysis(onset_s: float, rate: float, duration_d: float) -> Driver:
    """Red cell loss at `rate` (10^6/uL/d) for `duration_d` days."""
    def profile(t: float) -> float:
        return rate if t < duration_d * DAY_S else 0.0

    return Driver("haemolysis", onset_s, (Effect(ERYTHRO, "haemolysis_rate", "input", profile),))


def acute_kidney_injury(onset_s: float, depth: float, recovery_d: float) -> Driver:
    """GFR falls by `depth` (a fraction) at onset and recovers linearly over `recovery_d`."""
    def profile(t: float) -> float:
        return 1.0 - depth * max(0.0, 1.0 - t / (recovery_d * DAY_S))

    return Driver("acute_kidney_injury", onset_s,
                  (Effect(KIDNEY, "gfr_factor", "input", profile),))


def hypertension_progression(onset_s: float, resistance_rise_per_year: float) -> Driver:
    """Systemic resistance rising by a fraction per year."""
    def profile(t: float) -> float:
        return 1.0 + resistance_rise_per_year * t / YEAR_S

    return Driver("hypertension_progression", onset_s,
                  (Effect(HEART, "resistance_factor", "input", profile),))


def glycaemic_deterioration(onset_s: float, sensitivity_decline_per_year: float) -> Driver:
    """Insulin action on glucose utilisation and production falling exponentially."""
    def profile(t: float) -> float:
        return math.exp(-sensitivity_decline_per_year * t / YEAR_S)

    return Driver("glycaemic_deterioration", onset_s,
                  (Effect(GLUCOSE, "V_mX", "scale_param", profile),
                   Effect(GLUCOSE, "k_p3", "scale_param", profile)))


def sickle_cell_crisis(onset_s: float, duration_d: float, lifespan_factor: float,
                       haemolysis_rate: float) -> Driver:
    """Shortened red cell survival and extra haemolysis during a crisis."""
    def during(value: float, baseline: float) -> Profile:
        return lambda t: value if t < duration_d * DAY_S else baseline

    return Driver("sickle_cell_crisis", onset_s,
                  (Effect(ERYTHRO, "lifespan_factor", "input", during(lifespan_factor, 1.0)),
                   Effect(ERYTHRO, "haemolysis_rate", "input", during(haemolysis_rate, 0.0))))


def pregnancy(onset_s: float, weeks_at_onset: float) -> Driver:
    """Gestational age advancing from `weeks_at_onset`."""
    def weeks(t: float) -> float:
        return weeks_at_onset + t / WEEK_S

    return Driver("pregnancy", onset_s,
                  (Effect(MATERNAL, "gestation_weeks", "input", weeks),
                   Effect(PLACENTA, "gestation_weeks", "input", weeks)))
