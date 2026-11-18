"""Infection response (inventory item 9).

Four branches, each on its own time scale, merged onto one output grid:

- Malaria: the Hoshen et al. (2000) delay model of uninfected red cells, infected red cells
  and free merozoites, with a 48 h asexual cycle. Antimalarial treatment adds to the
  infected-cell kill rate.
- Bacterial infection (typhoid, urinary tract infection, pneumonia): the pathogen branch of
  the Reynolds et al. (2006) model with an antimicrobial kill rate.
- HIV: Perelson, Kirschner and De Boer (1993) model A of CD4 T cells and virus.
  Antiretroviral efficacy scales down the infection rate k_1.
- Tuberculosis: an activity state between 0 and 1 that rises in untreated active disease
  and falls on effective treatment (an assumption-based slow state).

Each treatment starts at its `*_start_d` input, in days from the start of the run.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import Any

import numpy as np
from scipy.integrate import solve_ivp

from ahdt.models.arrays import Array
from ahdt.models.base import AlgebraicModel, Inputs, ModelSpec, Params, Port
from ahdt.models.dde import integrate_dde
from ahdt.models.immune_lymphatic.inflammation import InflammationModel, reynolds_rhs
from ahdt.models.reference import person_value
from atra import contracts as c
from atra.connectors import DTKind

DAY_S = 86400.0
MALARIA_STEP_D = 0.005


def malaria(p: Params, rbc0: float, merozoites0: float, t_days: Array,
            kill: float = 0.0, kill_start_d: float = 0.0) -> Array:
    """Columns: uninfected red cells, infected red cells, free merozoites (per uL).

    The antimalarial kill rate adds to the infected-cell kill rate from `kill_start_d`.
    """
    mu = 1.0 / p["mal_rbc_lifespan"]
    lam = mu * rbc0
    beta, tau = p["mal_beta"], p["mal_tau"]

    def alpha(t: float) -> float:
        return p["mal_alpha"] + (kill if t >= kill_start_d else 0.0)

    def f(t: float, y: Array, lag: Any) -> list[float]:
        s_lag = float(lag(t - tau)[2])
        beta_star = beta * math.exp(-alpha(t) * tau)
        return [lam - mu * y[0] - beta * y[2],
                beta * y[2] - beta_star * s_lag - alpha(t) * y[1],
                p["mal_r"] * beta_star * s_lag - p["mal_delta"] * y[2] - beta * y[2]]

    zero = np.zeros(3)
    return integrate_dde(f, np.array([rbc0, 0.0, merozoites0]), t_days, MALARIA_STEP_D,
                         history=lambda s: zero)


def hiv(p: Params, t_days: Array, art_efficacy: float = 0.0, art_start_d: float = 0.0,
        y0: tuple[float, float, float, float] = (1000.0, 0.0, 0.0, 1e-3)) -> Array:
    """Columns: uninfected, latently infected and actively infected CD4 cells, virus.

    Antiretroviral efficacy scales down the infection rate from `art_start_d`.
    """

    def f(t: float, y: Array) -> list[float]:
        k1 = p["hiv_k_1"] * (1 - (art_efficacy if t >= art_start_d else 0.0))
        t_u, t_l, t_a, v = y
        total = t_u + t_l + t_a
        return [p["hiv_s"] + p["hiv_r"] * t_u - p["hiv_mu_T"] * t_u - k1 * v * t_u
                - p["hiv_r"] * t_u * total / p["hiv_T_max"],
                k1 * v * t_u - p["hiv_mu_T"] * t_l - p["hiv_k_2"] * t_l,
                p["hiv_k_2"] * t_l - p["hiv_mu_b"] * t_a,
                p["hiv_N"] * p["hiv_mu_b"] * t_a - k1 * v * t_u - p["hiv_mu_V"] * v]

    sol = solve_ivp(f, (0.0, float(t_days[-1])), np.array(y0), t_eval=t_days, method="LSODA",
                    rtol=1e-6, atol=1e-9)
    if not sol.success:
        raise RuntimeError(sol.message)
    return np.asarray(sol.y.T)


def tb_activity(p: Params, t_days: Array, active: bool, a0: float = 0.0,
                treatment_start_d: float | None = None) -> Array:
    """Rises towards 1 in active disease and decays from treatment start."""
    target = 1.0 if active else 0.0

    def untreated(t: Array | float) -> Array:
        return np.asarray(target + (a0 - target) * np.exp(-np.asarray(t) / p["tb_tau_active"]))

    out = untreated(t_days)
    if treatment_start_d is not None:
        at_start = float(untreated(treatment_start_d))
        after = t_days >= treatment_start_d
        out = np.where(after, at_start * np.exp(-(t_days - treatment_start_d)
                                                / p["tb_tau_treated"]), out)
    return out


class InfectionResponseModel(AlgebraicModel):
    spec = ModelSpec(
        model_id="ahdt.immune_lymphatic.infection_response",
        twin=DTKind.IMMUNE_LYMPHATIC, family=c.ModelFamily.SIMULATION, tier=c.Tier.T2,
        intended_use="Course of malaria, bacterial, HIV and TB infection under treatment",
        inputs=(Port("rbc", "10*6/uL", "field:789-8"),
                Port("merozoite_release", "/uL", "input:scenario"),
                Port("antimalarial_kill", "/d", "input:treatment"),
                Port("bacterial_inoculum", "1", "input:scenario"),
                Port("antimicrobial_kill", "/h", "input:treatment"),
                Port("hiv", "1", "input:condition"), Port("art_efficacy", "1", "input:treatment"),
                Port("tb_active", "1", "input:condition"),
                Port("tb_treatment_start_d", "d", "input:treatment")),
        outputs=(Port("parasitaemia", "%"), Port("parasite_density", "/uL"),
                 Port("haemolysis_rate", "10*6/uL/d"), Port("bacterial_load", "1"),
                 Port("cd4", "/mm3"), Port("viral_load", "/mm3"), Port("tb_activity", "1")),
        explainers=("counterfactual.scenario",))
    params_stem = "infection"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.reynolds = InflammationModel().base_params()

    def evaluate(self, p: Params, state: Mapping[str, Any], inputs: Inputs) -> dict[str, Any]:
        return {k: v for k, v in state.items() if k in {port.name for port in self.spec.outputs}}

    def run(self, p: Params, inputs: Mapping[str, Any], t_s: Array) -> dict[str, Array]:
        t_d = t_s / DAY_S
        out: dict[str, Array] = {}
        if inputs.get("merozoite_release"):
            rbc0 = float(person_value(inputs, "rbc")) * 1e6
            ys = malaria(p, rbc0, float(inputs["merozoite_release"]), t_d,
                         float(inputs.get("antimalarial_kill", 0.0)),
                         float(inputs.get("antimalarial_start_d", 0.0)))
            infected = ys[:, 1]
            out["parasite_density"] = infected
            out["parasitaemia"] = 100.0 * infected / (ys[:, 0] + infected)
            out["haemolysis_rate"] = p["mal_alpha"] * infected / 1e6
        if inputs.get("bacterial_inoculum"):
            kill = float(inputs.get("antimicrobial_kill", 0.0))
            start_h = float(inputs.get("antimicrobial_start_d", 0.0)) * 24.0
            y0 = [float(inputs["bacterial_inoculum"]), 0.0, 0.0,
                  self.reynolds["s_c"] / self.reynolds["mu_c"]]
            sol = solve_ivp(lambda t, y: reynolds_rhs(y, self.reynolds,
                                                      kill if t >= start_h else 0.0),
                            (0.0, t_s[-1] / 3600), y0, t_eval=t_s / 3600, method="LSODA")
            out["bacterial_load"] = sol.y[0]
        if inputs.get("hiv"):
            ys = hiv(p, t_d, float(inputs.get("art_efficacy", 0.0)),
                     float(inputs.get("art_start_d", 0.0)))
            out["cd4"] = ys[:, 0] + ys[:, 1] + ys[:, 2]
            out["viral_load"] = ys[:, 3]
        if inputs.get("tb_active") or inputs.get("tb_treatment_start_d") is not None:
            start = inputs.get("tb_treatment_start_d")
            out["tb_activity"] = tb_activity(p, t_d, bool(inputs.get("tb_active")),
                                             float(inputs.get("tb_activity0", 0.0)),
                                             None if start is None else float(start))
        return out

    def series(self, p: Params, state: Mapping[str, Any], t_s: Array, u: Any, *,
               param_path: Any = None, impulses: Any = ()) -> dict[str, Array]:
        """The branches run from the inputs at time zero; treatments start at their
        `*_start_d` inputs."""
        return self.run(p, u(0.0), t_s)
