"""Epidemic and public-health scenario models of the Population twin (design 04, 4.5.3).

The Ross-Macdonald model is the Smith-McKenzie form given in Smith et al. (2012), Box 7:

    dx/dt = m a b z (1 - x) - r x
    dz/dt = a c x (exp(-g v) - z) - g z

with x the share of infected humans and z the share of infectious mosquitoes. Vectorial
capacity is V = m a^2 exp(-g v) / g and the reproductive number R = V b c / r (same
source). The mosquito density m follows the season (rainy months April to October, the
months of the WP14b priors) and its rainy-season value is calibrated so that the annual mean
prevalence equals the kb Lagos prevalence (`prior.malaria_falciparum`). Parameter values and
their sources are in `epidemic.params.yaml`.

Interventions change the terms Smith et al. (2012, Box 8) attach to each mode of control:
nets lower the feeding rate a and raise the mosquito death rate g, a vaccine lowers b, and
treatment shortens the infection (r).
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from numpy.typing import NDArray
from scipy.integrate import solve_ivp
from scipy.optimize import brentq

from ahdt.models.ml.population import RAINY
from ahdt.models.params import ParamSet, load_params
from atra.config import get_settings
from atra.kb import KnowledgeBase

PARAMS = Path(__file__).with_name("epidemic.params.yaml")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
MONTH_DAYS = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)
YEAR_D = 365
BURN_IN_YEARS = 3

type F = NDArray[np.float64]


def _month_of_day() -> NDArray[np.int64]:
    return np.repeat(np.arange(12), MONTH_DAYS)


@lru_cache(maxsize=1)
def params() -> ParamSet:
    return load_params(PARAMS)


def target_prevalence(kb: KnowledgeBase | None = None) -> float:
    kb = kb or KnowledgeBase(get_settings().kb_dir)
    return float(kb.lookup("prior.malaria_falciparum", "prevalence_pct")) / 100.0


@dataclass(frozen=True)
class Intervention:
    """Coverage of each public-health measure, each in [0, 1]."""

    bednet_coverage: float = 0.0
    vaccine_coverage: float = 0.0
    treatment_coverage: float = 0.0

    def __post_init__(self) -> None:
        for name in ("bednet_coverage", "vaccine_coverage", "treatment_coverage"):
            if not 0.0 <= getattr(self, name) <= 1.0:
                raise ValueError(f"{name} must be in [0, 1]")

    @classmethod
    def of(cls, data: Mapping[str, Any] | None) -> Intervention:
        data = data or {}
        return cls(**{k: float(v) for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass(frozen=True)
class EpidemicResult:
    model: str
    intervention: Any
    day: F
    prevalence: F
    series: dict[str, F] = field(default_factory=dict)

    def summary(self) -> dict[str, float]:
        """Statistics of the last simulated year."""
        last = slice(max(0, len(self.day) - YEAR_D), None)
        x = self.prevalence[last]
        month = _month_of_day()[self.day[last].astype(int) % YEAR_D]
        rainy = np.isin(month, [MONTHS.index(m) for m in RAINY])
        out = {"mean_prevalence": float(x.mean()), "peak_prevalence": float(x.max()),
               "rainy_prevalence": float(x[rainy].mean()) if rainy.any() else math.nan,
               "dry_prevalence": float(x[~rainy].mean()) if (~rainy).any() else math.nan}
        if "eir" in self.series:
            out["annual_eir"] = float(self.series["eir"][last].mean() * YEAR_D)
        if "reproductive_number" in self.series:
            out["mean_reproductive_number"] = float(
                self.series["reproductive_number"][last].mean())
        return out


class EpidemicModel(Protocol):
    name: str

    def run(self, intervention: Any, days: int = YEAR_D) -> EpidemicResult: ...


@dataclass(frozen=True)
class _Rates:
    a: float
    b: float
    c: float
    g: float
    r: float
    v: float


class RossMacdonald:
    """Seasonal Ross-Macdonald malaria transmission for one region."""

    name = "ross_macdonald"

    def __init__(self, target: float | None = None, paramset: ParamSet | None = None) -> None:
        self.p = (paramset or params()).values
        self.target = target_prevalence() if target is None else target
        rainy = np.isin(_month_of_day(), [MONTHS.index(m) for m in RAINY])
        self.season: list[float] = np.where(rainy, 1.0, self.p["dry_season_factor"]).tolist()
        self.start: tuple[float, float] = (0.0, 0.0)
        self.m_rainy = self._calibrate()

    def rates(self, iv: Intervention) -> _Rates:
        p = self.p
        g0 = p["g"]
        a0 = p["stability_index"] * g0
        b0 = p["b_over_r"] * p["r"]
        a = a0 * (1.0 - iv.bednet_coverage * p["bednet_feeding_reduction"])
        g = g0 * (1.0 + iv.bednet_coverage * p["bednet_mortality_increase"])
        b = b0 * (1.0 - iv.vaccine_coverage * p["vaccine_efficacy"])
        r = (1.0 - iv.treatment_coverage) * p["r"] + iv.treatment_coverage / p[
            "treated_clearance_d"]
        return _Rates(a, b, p["c"], g, r, p["v"])

    def density(self, day: F, m_rainy: float) -> F:
        factor: F = np.asarray(self.season, dtype=float)[day.astype(int) % YEAR_D]
        return m_rainy * factor

    def mean_density(self, m_rainy: float) -> float:
        return m_rainy * float(np.mean(self.season))

    @staticmethod
    def equilibrium(m: float, k: _Rates) -> tuple[float, float]:
        """Endemic equilibrium (x, z) at a constant density `m`; (0, 0) when R <= 1."""
        surv = math.exp(-k.g * k.v)
        r0 = m * k.a ** 2 * k.b * k.c * surv / (k.g * k.r)
        if r0 <= 1.0:
            return 0.0, 0.0
        x = (r0 - 1.0) / (r0 + k.a * k.c / k.g)
        return x, k.a * k.c * x * surv / (k.a * k.c * x + k.g)

    def _solve(self, m_rainy: float, k: _Rates, days: int, y0: tuple[float, float],
               burn_in_d: int = 0) -> tuple[F, F, F]:
        """Daily (day, x, z) for `days` days after `burn_in_d` days, from state `y0`."""
        total = burn_in_d + days
        surv = math.exp(-k.g * k.v)
        season = self.season

        def rhs(t: float, y: F) -> list[float]:
            m = m_rainy * season[int(t) % YEAR_D]
            x, z = y
            return [m * k.a * k.b * z * (1 - x) - k.r * x,
                    k.a * k.c * x * (surv - z) - k.g * z]

        t_eval = np.arange(burn_in_d, total, dtype=float)
        sol = solve_ivp(rhs, (0.0, float(total)), list(y0), t_eval=t_eval,
                        method="LSODA", max_step=1.0, rtol=1e-6, atol=1e-12)
        if not sol.success:
            raise RuntimeError(f"Ross-Macdonald integration failed: {sol.message}")
        return t_eval - burn_in_d, sol.y[0], sol.y[1]

    def _seasonal_state(self, m_rainy: float) -> tuple[tuple[float, float], float]:
        """(state on 1 January of the periodic regime, its annual mean prevalence)."""
        k = self.rates(Intervention())
        y0 = self.equilibrium(self.mean_density(m_rainy), k)
        if y0[0] == 0.0:
            return y0, 0.0
        _, x, z = self._solve(m_rainy, k, YEAR_D + 1, y0, BURN_IN_YEARS * YEAR_D)
        return (float(x[-1]), float(z[-1])), float(x[:-1].mean())

    def _calibrate(self) -> float:
        k = self.rates(Intervention())
        surv = math.exp(-k.g * k.v)
        x = self.target
        # Mosquito density at which the constant-season equilibrium is the target.
        r0 = (1.0 + x * k.a * k.c / k.g) / (1.0 - x)
        m_mean = r0 * k.g * k.r / (k.a ** 2 * k.b * k.c * surv)
        guess = m_mean / float(np.mean(self.season))
        m_rainy = math.exp(brentq(lambda lm: self._seasonal_state(math.exp(lm))[1] - x,
                                  math.log(guess * 0.8), math.log(guess * 1.25), xtol=1e-7))
        self.start, _ = self._seasonal_state(m_rainy)
        return m_rainy

    def run(self, intervention: Intervention, days: int = YEAR_D) -> EpidemicResult:
        """`days` days from 1 January, starting in the calibrated endemic state."""
        k = self.rates(intervention)
        day, x, z = self._solve(self.m_rainy, k, days, self.start)
        m = self.density(day, self.m_rainy)
        capacity = m * k.a ** 2 * math.exp(-k.g * k.v) / k.g
        return EpidemicResult(self.name, intervention, day, x, {
            "sporozoite_rate": z, "eir": m * k.a * z, "vectorial_capacity": capacity,
            "reproductive_number": capacity * k.b * k.c / k.r})


@dataclass(frozen=True)
class RespiratoryScenario:
    """Covasim measures: symptomatic testing, contact tracing and day-0 vaccination."""

    test_prob: float = 0.0
    trace_prob: float = 0.0
    vaccine_coverage: float = 0.0

    @classmethod
    def of(cls, data: Mapping[str, Any] | None) -> RespiratoryScenario:
        data = data or {}
        return cls(**{k: float(v) for k, v in data.items() if k in cls.__dataclass_fields__})


class CovasimRespiratory:
    """Agent-based respiratory epidemic (Covasim 4 with its default COVID-19 parameters)."""

    name = "covasim"

    def __init__(self, pop_size: int = 2000, seed: int = 1) -> None:
        self.pop_size = pop_size
        self.seed = seed

    def run(self, intervention: RespiratoryScenario, days: int = 120) -> EpidemicResult:
        import covasim as cv

        ivs: list[Any] = []
        if intervention.test_prob > 0:
            ivs.append(cv.test_prob(symp_prob=intervention.test_prob))
            if intervention.trace_prob > 0:
                ivs.append(cv.contact_tracing(trace_probs=intervention.trace_prob))
        if intervention.vaccine_coverage > 0:
            ivs.append(cv.vaccinate_prob(vaccine="default", days=0,
                                         prob=intervention.vaccine_coverage))
        sim = cv.Sim(pop_size=self.pop_size, n_days=days, rand_seed=self.seed, verbose=0,
                     interventions=ivs)
        sim.run()
        res = sim.results
        prevalence = np.asarray(res["prevalence"], dtype=float)
        return EpidemicResult(self.name, intervention, np.arange(len(prevalence), dtype=float),
                              prevalence, {
                                  "new_infections": np.asarray(res["new_infections"], dtype=float),
                                  "cum_infections": np.asarray(res["cum_infections"], dtype=float)})


def default_scenario(model: EpidemicModel) -> Any:
    return RespiratoryScenario() if isinstance(model, CovasimRespiratory) else Intervention()


def compare(model: EpidemicModel, scenarios: Mapping[str, Any],
            days: int = 3 * YEAR_D) -> dict[str, dict[str, float]]:
    """Summary of each scenario with its change in mean prevalence against no intervention."""
    base = model.run(default_scenario(model), days).summary()
    out = {"baseline": base}
    for name, iv in scenarios.items():
        s = model.run(iv, days).summary()
        s["prevalence_reduction"] = 1.0 - s["mean_prevalence"] / base["mean_prevalence"]
        out[name] = s
    return out
