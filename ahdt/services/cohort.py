"""`ahdt.data.cohort_extract`: de-identified data products (design 04, 4.7.2).

Only persons whose consent covers the caller's purpose of use enter a cohort. With
`KAnonymity` the rows are generalised (age to 5-year bands, address to state, a measurement
to low, normal or high against its reference range) and every group smaller than k is
suppressed, with k at least `privacy.k_min`. With `DifferentialPrivacy` the result is a set of
aggregates under the Laplace mechanism. The request's epsilon is split equally over the
released statistics and charged to the caller, whose total is capped by
`privacy.epsilon_budget`.
"""

from __future__ import annotations

import math
import threading
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
from pydantic import BaseModel

from ahdt.knowledge.documents import PARTITION as FHIR_PARTITION
from ahdt.models.reference import default_kb
from ahdt.services.runtime import Runtime
from atra.kb import KBError
from atra.service import Identity, Problem, ToolHandler

AGE_BAND_YEARS = 5
SNOMED = "http://snomed.info/sct"
STATS_PER_FIELD = 2


class PrivacyLedger:
    """Epsilon spent per caller under basic composition."""

    def __init__(self, budget: float) -> None:
        self.budget = budget
        self._spent: dict[str, float] = {}
        self._lock = threading.Lock()

    def charge(self, who: str, epsilon: float) -> float:
        with self._lock:
            spent = self._spent.get(who, 0.0)
            if spent + epsilon > self.budget + 1e-12:
                raise Problem(403, "forbidden",
                              f"the privacy budget of {self.budget:g} is used up "
                              f"({spent:g} spent)")
            self._spent[who] = spent + epsilon
            return self.budget - self._spent[who]

    def spent(self, who: str) -> float:
        with self._lock:
            return self._spent.get(who, 0.0)


def laplace(scale: float, rng: np.random.Generator) -> float:
    """One draw from Laplace(0, scale) by inverse transform sampling."""
    u = float(rng.random()) - 0.5
    return -scale * math.copysign(1.0, u) * math.log(1 - 2 * abs(u))


def age_band(birth: date, today: date) -> str:
    years = today.year - birth.year - ((today.month, today.day) < (birth.month, birth.day))
    low = max(years, 0) // AGE_BAND_YEARS * AGE_BAND_YEARS
    return f"{low}-{low + AGE_BAND_YEARS - 1}"


class CohortService:
    def __init__(self, runtime: Runtime, *, seed: int | None = None) -> None:
        self.rt = runtime
        kb = default_kb()
        self.k_min = int(kb.resolve("privacy.k_min"))
        self.ledger = PrivacyLedger(float(kb.resolve("privacy.epsilon_budget")))
        self.rng = np.random.default_rng(seed)

    async def _people(self, purpose: str) -> list[str]:
        pipe = await self.rt.pipeline()
        rows = pipe.lake.query("SELECT DISTINCT hdt_id FROM observations")
        out = []
        for row in rows:
            consent = self.rt.consents.get(row["hdt_id"])
            if consent is not None and purpose in consent.purposes:
                out.append(str(row["hdt_id"]))
        return sorted(out)

    async def _has_condition(self, hdt_id: str, code: str) -> bool:
        pipe = await self.rt.pipeline()
        found = await pipe.backends.fhir.search(
            "Condition", {"subject": f"Patient/{hdt_id}", "code": code}, partition=FHIR_PARTITION)
        return bool(found)

    async def _patient(self, hdt_id: str) -> Mapping[str, Any]:
        pipe = await self.rt.pipeline()
        try:
            return await pipe.backends.fhir.read("Patient", hdt_id, partition=FHIR_PARTITION)
        except (KeyError, LookupError):
            return {}

    async def _row(self, hdt_id: str, fields: Sequence[str], latest: Mapping[str, Any]
                   ) -> dict[str, Any]:
        patient = await self._patient(hdt_id)
        row: dict[str, Any] = {}
        for name in fields:
            if name == "age_band":
                birth = patient.get("birthDate")
                row[name] = (age_band(date.fromisoformat(birth), datetime.now(UTC).date())
                             if birth else "unknown")
            elif name == "state":
                row[name] = ((patient.get("address") or [{}])[0].get("state") or "unknown")
            else:
                row[name] = latest.get(name)
        return row

    def _level(self, name: str, value: Any) -> Any:
        """A measurement as low, normal or high against its reference range."""
        if value is None:
            return "unknown"
        if not isinstance(value, int | float):
            return str(value)
        low = self._range(name, "ref_low")
        high = self._range(name, "ref_high")
        if low is not None and value < low:
            return "low"
        return "high" if high is not None and value > high else "normal"

    @staticmethod
    def _range(name: str, key: str) -> float | None:
        try:
            value = default_kb().lookup(f"range.{name}", key)
        except KBError:
            raise Problem(422, "invalid-arguments", f"{name} has no reference range") from None
        return None if value is None else float(value)

    async def extract(self, args: BaseModel, ident: Identity) -> dict[str, Any]:
        a: Any = args
        known = {"condition", "where"}
        unknown = set(a.cohort_def) - known
        if unknown:
            raise Problem(422, "invalid-arguments",
                          f"unknown cohort_def keys: {', '.join(sorted(unknown))}")
        reader = await self.rt.reader()
        fields: list[str] = list(a.fields)
        where: Mapping[str, Mapping[str, float]] = a.cohort_def.get("where", {})
        measured = {f for f in (*fields, *where) if f not in ("age_band", "state")}
        rows: list[dict[str, Any]] = []
        for hdt_id in await self._people(ident.ctx.purpose):
            code = a.cohort_def.get("condition")
            if code and not await self._has_condition(hdt_id, str(code)):
                continue
            latest = {}
            for reading in reader.latest(hdt_id, as_of=a.as_of).values():
                name = reader.field_name(reading.code)
                if name in measured and isinstance(reading.value, float):
                    latest[name] = reading.value
            if not all(self._within(latest.get(f), bound) for f, bound in where.items()):
                continue
            rows.append(await self._row(hdt_id, fields, latest))
        if hasattr(a.privacy, "k"):
            return self._k_anonymous(rows, fields, int(a.privacy.k))
        return self._private_aggregates(rows, fields, float(a.privacy.epsilon), ident)

    @staticmethod
    def _within(value: float | None, bound: Mapping[str, float]) -> bool:
        if value is None:
            return False
        return (value >= bound.get("gte", -math.inf) and value <= bound.get("lte", math.inf))

    def _k_anonymous(self, rows: list[dict[str, Any]], fields: list[str], k: int
                     ) -> dict[str, Any]:
        k_eff = max(k, self.k_min)
        general = [{f: self._level(f, v) if f not in ("age_band", "state") else v
                    for f, v in r.items()} for r in rows]
        groups = Counter(tuple(r[f] for f in fields) for r in general)
        kept = [r for r in general if groups[tuple(r[f] for f in fields)] >= k_eff]
        return {"rows": kept,
                "privacy_report": {"method": "k-anonymity", "k": k_eff, "requested_k": k,
                                   "input_rows": len(rows), "released": len(kept),
                                   "suppressed": len(rows) - len(kept),
                                   "generalised": [f for f in fields
                                                   if f not in ("age_band", "state")]}}

    def _private_aggregates(self, rows: list[dict[str, Any]], fields: list[str],
                            epsilon: float, ident: Identity) -> dict[str, Any]:
        remaining = self.ledger.charge(ident.ctx.actor_id, epsilon)
        categorical = [f for f in fields if f in ("age_band", "state")]
        numeric = [f for f in fields if f not in categorical]
        statistics = 1 + len(categorical) + STATS_PER_FIELD * len(numeric)
        share = epsilon / statistics
        out: dict[str, Any] = {"count": max(0.0, len(rows) + laplace(1 / share, self.rng))}
        for f in categorical:
            counts = Counter(r[f] for r in rows)
            out[f] = {key: max(0.0, n + laplace(1 / share, self.rng))
                      for key, n in sorted(counts.items())}
        for f in numeric:
            lo = self._range(f, "crit_low")
            hi = self._range(f, "crit_high")
            if lo is None or hi is None:
                raise Problem(422, "invalid-arguments",
                              f"{f} has no bounds for a private mean")
            values = [min(max(float(r[f]), lo), hi) for r in rows if r[f] is not None]
            half = STATS_PER_FIELD * share / 2
            noisy_sum = sum(values) + laplace(max(abs(lo), abs(hi)) / half, self.rng)
            noisy_n = len(values) + laplace(1 / half, self.rng)
            out[f] = {"mean": noisy_sum / max(noisy_n, 1.0), "clip": [lo, hi]}
        return {"aggregates": out,
                "privacy_report": {"method": "laplace", "epsilon": epsilon,
                                   "epsilon_remaining": remaining, "statistics": statistics}}

    def handlers(self) -> dict[str, ToolHandler]:
        return {"ahdt.data.cohort_extract": self.extract}
