"""De-identified contribution receiver and cohort store (design 04, 4.5.3; design 07, 7.2).

A contribution is a `cohort_contribution` (Whole-Body, `IndividualToPopulationConnector`)
or a `registry_case` (APDT, `RegistryContributionConnector`) record. The receiver
validates it against its connector contract, keeps only the contract fields, and stores
it only when its equivalence class (age band, sex, state) holds at least k records,
counting the stored records of that class (k-anonymity, k from `kb/privacy.yaml`). A
record of a smaller class waits in memory until its class reaches k. Stored records go to
the Iceberg table `lake.contributions`, which the cohort statistics read with DuckDB.
"""

from __future__ import annotations

import json
import re
import threading
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from pyiceberg.types import DoubleType, StringType, TimestamptzType

from ahdt.stores.lake import Lake
from atra.connector_contracts import REGISTRY_CASE
from atra.connectors import ContractViolation, DataContract, IndividualToPopulationConnector
from atra.ids import new_record_id
from atra.kb import KnowledgeBase

CONTRACTS: Mapping[str, DataContract] = {
    "cohort_contribution": IndividualToPopulationConnector.OUT_CONTRACT,
    "registry_case": REGISTRY_CASE,
}
QUASI_IDENTIFIERS = ("age_band", "sex", "state")
_FIVE_YEAR = re.compile(r"^\d+-\d+$")

CONTRIBUTION_COLUMNS: tuple[tuple[str, Any, bool], ...] = (
    ("contribution_id", StringType(), True),
    ("contract", StringType(), True),
    ("age_band", StringType(), True),
    ("sex", StringType(), True),
    ("state", StringType(), True),
    ("conditions", StringType(), True),
    ("condition", StringType(), False),
    ("outcome", StringType(), False),
    ("bmi", DoubleType(), False),
    ("ingested_at", TimestamptzType(), True),
    ("ingested_day", StringType(), True),
)
TABLES = {"contributions": CONTRIBUTION_COLUMNS}

type Contract = Literal["cohort_contribution", "registry_case"]


def k_min(kb: KnowledgeBase) -> int:
    return int(kb.resolve("privacy.k_min"))


@dataclass(frozen=True)
class Receipt:
    accepted: int
    suppressed: int
    k: int


def generalise(contract: Contract, record: Mapping[str, Any]) -> dict[str, Any]:
    """The contract fields of a validated record, with a five-year age band."""
    spec = CONTRACTS[contract]
    out = {name: record[name] for name in spec.fields if record.get(name) is not None}
    try:
        spec.validate(out)
    except ContractViolation as exc:
        raise ValueError(str(exc)) from None
    if not _FIVE_YEAR.match(str(out["age_band"])):
        raise ValueError(f"age_band {out['age_band']!r} is not an age band")
    return out


class CohortStore:
    """k-anonymous contributions over the population lake."""

    def __init__(self, directory: Path, k: int) -> None:
        self.lake = Lake(directory, TABLES)
        self.k = k
        self._lock = threading.Lock()
        self._pending: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
        self._stored = Counter(tuple(r[q] for q in QUASI_IDENTIFIERS)
                               for r in self.lake.arrow("contributions").to_pylist())

    def contribute(self, contract: Contract, records: Sequence[Mapping[str, Any]],
                   *, now: datetime | None = None) -> Receipt:
        clean = [generalise(contract, r) for r in records]
        now = now or datetime.now(UTC)
        with self._lock:
            for rec in clean:
                self._pending[tuple(str(rec[q]) for q in QUASI_IDENTIFIERS)].append(rec)
            ready: list[dict[str, Any]] = []
            for cls, waiting in list(self._pending.items()):
                if self._stored[cls] + len(waiting) >= self.k:
                    ready += [self._row(contract, r, now) for r in waiting]
                    self._stored[cls] += len(waiting)
                    del self._pending[cls]
            self.lake.append("contributions", ready)
            held = sum(len(v) for v in self._pending.values())
        return Receipt(accepted=len(ready), suppressed=held, k=self.k)

    @staticmethod
    def _row(contract: str, r: Mapping[str, Any], now: datetime) -> dict[str, Any]:
        return {"contribution_id": new_record_id(), "contract": contract,
                "age_band": str(r["age_band"]), "sex": str(r["sex"]), "state": str(r["state"]),
                "conditions": json.dumps(sorted(r.get("conditions") or [])),
                "condition": r.get("condition"), "outcome": r.get("outcome"),
                "bmi": r.get("bmi"), "ingested_at": now}

    def pending(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._pending.values())

    def cohort_size(self) -> int:
        return int(self.lake.query("SELECT count(*) AS n FROM contributions",
                                   table="contributions")[0]["n"])

    def condition_counts(self) -> list[dict[str, Any]]:
        """Cases by condition, age band and sex; cells under k are suppressed."""
        rows = self.lake.query(
            "SELECT c.condition, age_band, sex, count(*) AS n FROM ("
            " SELECT unnest(CAST(json_extract_string(conditions, '$[*]') AS VARCHAR[]))"
            " AS condition, age_band, sex FROM contributions"
            " WHERE contract = 'cohort_contribution'"
            " UNION ALL SELECT condition, age_band, sex FROM contributions"
            " WHERE contract = 'registry_case') c"
            " GROUP BY ALL ORDER BY ALL", table="contributions")
        return [r | {"n": r["n"] if r["n"] >= self.k else None} for r in rows]
