"""Federated update of the population priors with differential privacy (design 04, 4.5.3).

Each tenant is a client. A client counts its own de-identified records per cell
(`count_table` of the WP14b priors model), adds Laplace noise of scale 1/epsilon to every
count before it leaves the tenant, and sends the noisy table. The server pools the tables
(`federated_merge` without further noise, which is federated averaging of the tables by
record count) and adds them to the prior tables.

Accounting. One person changes one cell of each condition table, by one in both the case
and the person count. With noise of scale 1/epsilon on each count, one condition table
costs 2 epsilon per person (L1 sensitivity 2), cells compose in parallel, and the condition
tables of a round compose sequentially. A person with `records_per_person` rows (for
example person-months) multiplies the cost. The ledger charges this per tenant and refuses
a round that would exceed the tenant's budget (`kb/privacy.yaml`).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import numpy as np
import pandas as pd

from ahdt.models.ml.population import count_table, federated_merge
from atra.kb import KnowledgeBase
from population.priors import PopulationPriors

KEYS = ("age_band", "sex", "season", "region")

type CountTable = dict[str, dict[str, list[float]]]


class BudgetExceeded(RuntimeError):
    """A release would spend more epsilon than the requester has left."""


@dataclass(frozen=True)
class Charge:
    requester: str
    epsilon: float
    purpose: str
    at: datetime


@dataclass
class PrivacyLedger:
    """Epsilon spent per requester (tenant or researcher) under basic composition."""

    budget: float
    charges: list[Charge] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    @classmethod
    def from_kb(cls, kb: KnowledgeBase) -> PrivacyLedger:
        return cls(float(kb.resolve("privacy.epsilon_budget")))

    def spent(self, requester: str) -> float:
        return sum(c.epsilon for c in self.charges if c.requester == requester)

    def remaining(self, requester: str) -> float:
        return self.budget - self.spent(requester)

    def charge(self, costs: Mapping[str, float], purpose: str) -> list[Charge]:
        """Charge every requester at once, or none of them."""
        with self._lock:
            over = [r for r, eps in costs.items() if self.spent(r) + eps > self.budget + 1e-12]
            if over:
                raise BudgetExceeded(f"privacy budget exceeded for {', '.join(sorted(over))}")
            now = datetime.now(UTC)
            new = [Charge(r, eps, purpose, now) for r, eps in costs.items()]
            self.charges += new
            return new


def round_cost(epsilon: float, conditions: int, records_per_person: int = 1) -> float:
    return 2.0 * epsilon * conditions * records_per_person


@dataclass(frozen=True)
class TenantClient:
    """One tenant's records; only its noisy count table leaves the tenant."""

    tenant: str
    rows: pd.DataFrame
    records_per_person: int = 1

    def fit(self, conditions: Sequence[str], epsilon: float,
            rng: np.random.Generator) -> CountTable:
        table = count_table(self.rows, KEYS, conditions)
        return federated_merge([table], epsilon, rng)


@dataclass(frozen=True)
class RoundReport:
    round: int
    tenants: list[str]
    conditions: list[str]
    epsilon_per_cell: float
    epsilon_spent: dict[str, float]
    epsilon_remaining: dict[str, float]
    budget: float
    cells: int
    persons: float
    mechanism: str = "Laplace, scale 1/epsilon per count, added by each tenant"
    aggregation: str = "federated sum of tenant count tables (numpy)"

    def to_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


def run_round(priors: PopulationPriors, clients: Sequence[TenantClient],
              conditions: Sequence[str], ledger: PrivacyLedger, *, epsilon: float,
              seed: int = 0) -> RoundReport:
    """One federated round: charge the ledger, collect noisy tables, pool, update priors."""
    costs = {c.tenant: round_cost(epsilon, len(conditions), c.records_per_person)
             for c in clients}
    ledger.charge(costs, "population.priors federated round")
    rng = np.random.default_rng(seed)
    tables = [c.fit(conditions, epsilon, rng) for c in clients]
    pooled = federated_merge(tables, None, rng)
    number = priors.rounds + 1
    priors.merge(pooled, f"federated round {number} (epsilon {epsilon} per cell)")
    return RoundReport(
        round=number, tenants=[c.tenant for c in clients], conditions=list(conditions),
        epsilon_per_cell=epsilon, epsilon_spent={t: ledger.spent(t) for t in costs},
        epsilon_remaining={t: ledger.remaining(t) for t in costs}, budget=ledger.budget,
        cells=sum(len(cells) for cells in pooled.values()),
        persons=float(sum(n for _, n in next(iter(pooled.values())).values())) if pooled
        else 0.0)
