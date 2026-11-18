"""Population priors and norms served to every HDT (design 04, 4.5.3; design 03, 3.16).

Priors come from the pooled count table of the WP14b priors model
(`ahdt.population.population_priors_and_norms`), updated by each federated round
(`population.federated`). A cell is `age_band|sex|season|region`; chronic conditions have
the season `all`. A condition the table does not hold falls back to its kb seed
(`kb/priors.yaml`), scaled by the one-way sex and month breakdowns (`prior.combination`).

Norms are the field percentiles (p05, p50, p95) by age band and sex of the same model.
"""

from __future__ import annotations

import json
import re
import threading
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ahdt.models.ml.artifacts import model_dir
from ahdt.models.ml.common import age_band
from ahdt.models.ml.population import RAINY, prevalence_tables
from ahdt.models.ml.slices import bands, config, region_of
from ahdt.registry import Registry, load_registry
from atra.kb import KBError, KnowledgeBase

MODEL_ID = "ahdt.population.population_priors_and_norms"
SEASONS = ("dry", "rainy")
_FIVE_YEAR = re.compile(r"^(\d+)-(\d+)$")

type CountTable = dict[str, dict[str, list[float]]]


class UnknownCondition(KeyError):
    """No pooled table and no kb seed for the condition."""


class UnknownNorm(KeyError):
    """No percentiles for the field in that age band and sex."""


def artifact(root: Path | None = None) -> Path:
    return model_dir(MODEL_ID, root) / "priors.json"


def slice_age_band(value: str) -> str:
    """The WP14b reporting band of an age band label (`45-49` or `40-59`) or an age."""
    labels = {b[0] for b in bands()}
    if value in labels:
        return value
    match = _FIVE_YEAR.match(value)
    if match:
        return age_band(float(match.group(1)), bands())
    try:
        return age_band(float(value), bands())
    except ValueError:
        raise ValueError(f"unknown age band {value!r}") from None


def slice_region(value: str) -> str:
    """The reporting region of a region name or a Lagos LGA."""
    if value in config()["region"]["groups"]:
        return value
    return region_of(value)


@dataclass(frozen=True)
class Prior:
    condition: str
    prevalence: float
    age_band: str
    season: str
    region: str
    source: str

    def row(self) -> dict[str, Any]:
        return {"condition": self.condition, "prevalence": self.prevalence,
                "age_band": self.age_band, "season": self.season, "region": self.region,
                "source": self.source}


class PopulationPriors:
    """The current prior and norm tables, replaced as a whole by each federated round."""

    def __init__(self, data: Mapping[str, Any], kb: KnowledgeBase, *, version: str,
                 registry: Registry | None = None) -> None:
        self.kb = kb
        self.version = version
        self.registry = registry or load_registry()
        self._lock = threading.Lock()
        dp = data["tables"]["dp"]
        self.counts: CountTable = {c: {k: list(v) for k, v in cells.items()}
                                   for c, cells in dp["counts"].items()}
        self.norms: dict[str, dict[str, list[float]]] = data["norms"]
        self.source = f"{MODEL_ID} {version} (epsilon {data['epsilon']})"
        self.rounds = 0
        self._recompute()

    @classmethod
    def load(cls, kb: KnowledgeBase, root: Path | None = None) -> PopulationPriors:
        """The trained tables, or the kb seeds alone when the model is not trained."""
        path = artifact(root)
        if not path.exists():
            return cls({"tables": {"dp": {"counts": {}}}, "norms": {}, "epsilon": None}, kb,
                       version="untrained")
        data = json.loads(path.read_text(encoding="utf-8"))
        metrics = json.loads((path.parent / "metrics.json").read_text(encoding="utf-8"))
        return cls(data, kb, version=str(metrics["version"]))

    def _recompute(self) -> None:
        self.prevalence, self.overall = prevalence_tables(self.counts)

    def merge(self, pooled: Mapping[str, Mapping[str, Sequence[float]]], source: str) -> None:
        """Add a federated round's pooled counts to the table."""
        with self._lock:
            for cond, cells in pooled.items():
                table = self.counts.setdefault(cond, {})
                for key, (k, n) in cells.items():
                    acc = table.setdefault(key, [0.0, 0.0])
                    acc[0] += float(k)
                    acc[1] += float(n)
            self.rounds += 1
            self.source = source
            self._recompute()

    def condition_id(self, code: str) -> str:
        """The kb condition id of a kb id or a SNOMED CT code."""
        if code in self.kb:
            return code
        for entry_id in (i for i in self.kb.ids() if i.startswith("cond.")):
            if str(self.kb.entry(entry_id).content().get("snomed")) == code:
                return entry_id
        raise UnknownCondition(code)

    def prior(self, condition: str, age_band: str, sex: str, season: str,
              region: str) -> Prior:
        condition = self.condition_id(condition)
        if season not in SEASONS:
            raise ValueError(f"unknown season {season!r}")
        band, group = slice_age_band(age_band), slice_region(region)
        table = self.prevalence.get(condition)
        if table is not None:
            for s in (season, "all"):
                value = table.get(f"{band}|{sex}|{s}|{group}")
                if value is not None:
                    return Prior(condition, value, age_band, season, region, self.source)
        return self._seed(condition, age_band, sex, season, region)

    def _seed(self, condition: str, age_band: str, sex: str, season: str,
              region: str) -> Prior:
        entry_id = "prior." + condition.removeprefix("cond.")
        try:
            content = self.kb.entry(entry_id).content()
        except KBError:
            raise UnknownCondition(condition) from None
        if "prevalence_pct" not in content:
            raise UnknownCondition(condition)
        base = float(content["prevalence_pct"])
        reference = float(content.get("national_pct", base))
        value = base
        if sex in content.get("by_sex_pct", {}):
            value *= float(content["by_sex_pct"][sex]) / reference
        months = [float(v) for m, v in content.get("by_month_pct", {}).items()
                  if (m in RAINY) == (season == "rainy")]
        if months:
            value *= sum(months) / len(months) / reference
        return Prior(condition, min(value / 100.0, 1.0), age_band, season, region,
                     f"kb:{entry_id}")

    def norm(self, field: str, age_band: str, sex: str) -> dict[str, Any]:
        cell = self.norms.get(field, {}).get(f"{slice_age_band(age_band)}|{sex}")
        if cell is None:
            raise UnknownNorm(field)
        p05, p50, p95, n = cell
        return {"field": field, "unit": self.unit_of(field), "p05": p05, "p50": p50,
                "p95": p95, "n": int(n)}

    def unit_of(self, field: str) -> str:
        for twin in self.registry.twins.values():
            for f in twin.fields:
                if f.name == field:
                    return f.ucum
        return "1"
