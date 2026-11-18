"""Population twin T1 models: cohort statistics and population priors and norms.

- Cohort: cohort definitions evaluated over contributed, de-identified records (age band,
  sex, region and conditions only), with small cells suppressed. Validation: the cohort
  prevalence of each chronic condition against the mean WP02 prior probability of the same
  persons.
- Priors and norms: prevalence by condition x age band x sex x season x region, shrunk to
  the condition x age band x sex margin (Beta prior of strength `STRENGTH`), and field
  percentiles (p05, p50, p95) by age band x sex. Tenants contribute count tables; the
  federated update adds Laplace noise to each tenant's counts (epsilon-differential privacy
  per cell, one record per person) and pools them. Validation on held-out persons: the
  Brier score of the prior against the overall prevalence, and the share of field values
  inside p05 to p95.
"""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray

from ahdt.models.ml.artifacts import Result, write_result
from ahdt.models.ml.common import split_of
from evaluation.models.ahdt.fairness import ATTRIBUTES, slice_report

MIN_CELL = 5
STRENGTH = 20.0
EPSILON = 1.0
CONDITIONS = ("cond.hypertension", "cond.diabetes_type2", "cond.hiv")
MALARIA = "cond.malaria_falciparum"
RAINY = ("apr", "may", "jun", "jul", "aug", "sep", "oct")
COHORTS: Sequence[Mapping[str, Any]] = (
    {"id": "adults_hypertension", "min_age": 18, "condition": "cond.hypertension"},
    {"id": "adults_diabetes", "min_age": 18, "condition": "cond.diabetes_type2"},
    {"id": "adults_hiv", "min_age": 15, "condition": "cond.hiv"},
    {"id": "under_five", "max_age": 5},
    {"id": "older_adults", "min_age": 60},
)


def deidentify(persons: pd.DataFrame) -> pd.DataFrame:
    """The contributed record: no identifiers, ages as bands."""
    keep = ["age_band", "sex", "region", "facility_level", "age_years", *CONDITIONS]
    return persons[keep].assign(age_years=lambda d: (d.age_years // 5) * 5)


def cohort_stats(records: pd.DataFrame) -> dict[str, dict[str, Any]]:
    out = {}
    for c in COHORTS:
        m = np.ones(len(records), dtype=bool)
        if "min_age" in c:
            m &= records.age_years.to_numpy() >= c["min_age"]
        if "max_age" in c:
            m &= records.age_years.to_numpy() < c["max_age"]
        base = int(m.sum())
        if "condition" in c:
            m &= records[c["condition"]].to_numpy(dtype=bool)
        n = int(m.sum())
        sub = records[m]
        by_sex = sub.sex.value_counts().to_dict()
        out[c["id"]] = {
            "definition": dict(c), "n": n if n >= MIN_CELL else None,
            "share_of_base": (n / base) if base and n >= MIN_CELL else None,
            "by_sex": {k: (int(v) if v >= MIN_CELL else None) for k, v in by_sex.items()},
            "age_band_counts": {k: (int(v) if v >= MIN_CELL else None)
                                for k, v in sub.age_band.value_counts().items()}}
    return out


def train_cohort(model_id: str, version: str, persons: pd.DataFrame, truth: pd.DataFrame,
                 out: Path) -> Result:
    """`persons`: one row per person with slices and condition indicators; `truth`: the
    WP02 prior probability of each condition per person (same index)."""
    records = deidentify(persons)
    stats = cohort_stats(records)
    cell = ["age_band", "sex"]
    errors = {}
    est_cols = {}
    for cond in CONDITIONS:
        est = records.groupby(cell)[cond].transform("mean")
        est_cols[cond] = est.to_numpy()
        errors[cond] = abs(float(records[cond].mean()) - float(truth[cond].mean()))
    metrics = {f"prevalence_abs_error.{c}": e for c, e in errors.items()}
    metrics["max_prevalence_abs_error"] = max(errors.values())
    cond = CONDITIONS[0]
    report = slice_report(model_id, "regression", truth[cond].to_numpy(), est_cols[cond],
                          {a: persons[a].tolist() for a in ATTRIBUTES if a in persons})
    out.mkdir(parents=True, exist_ok=True)
    (out / "cohorts.json").write_text(json.dumps({"min_cell": MIN_CELL, "cohorts": stats},
                                                 indent=1), encoding="utf-8")
    result = Result(model_id, version, "atra-synthetic-population (WP02 generator)",
                    "max_prevalence_abs_error", metrics["max_prevalence_abs_error"], metrics,
                    report.to_dict(), split={"persons": len(persons), "unit": "person"},
                    notes=[f"Cells under {MIN_CELL} records are suppressed.",
                           f"Slice MAE compares the age band x sex cohort prevalence of {cond} "
                           "with each person's WP02 prior probability."])
    write_result(result, out, fairness_md=report.markdown())
    return result


def _season(month: str) -> str:
    return "rainy" if month in RAINY else "dry"


def count_table(rows: pd.DataFrame, keys: Sequence[str], conditions: Sequence[str]
                ) -> dict[str, dict[str, list[float]]]:
    """{condition: {cell key: [cases, persons]}} over `keys`."""
    out: dict[str, dict[str, list[float]]] = defaultdict(dict)
    for cond in conditions:
        g = rows.groupby(list(keys))[cond].agg(["sum", "count"])
        for k, r in g.iterrows():
            key = "|".join(map(str, k if isinstance(k, tuple) else (k,)))
            out[cond][key] = [float(r["sum"]), float(r["count"])]
    return dict(out)


def federated_merge(tables: Sequence[Mapping[str, Mapping[str, Sequence[float]]]],
                    epsilon: float | None, rng: np.random.Generator
                    ) -> dict[str, dict[str, list[float]]]:
    """Pool tenant count tables; each tenant adds Laplace(1/epsilon) noise to its counts."""
    pooled: dict[str, dict[str, list[float]]] = defaultdict(dict)
    for table in tables:
        for cond, cells in table.items():
            for key, (k, n) in cells.items():
                if epsilon is not None:
                    k = max(0.0, k + rng.laplace(0, 1.0 / epsilon))
                    n = max(k, n + rng.laplace(0, 1.0 / epsilon))
                acc = pooled[cond].setdefault(key, [0.0, 0.0])
                acc[0] += k
                acc[1] += n
    return dict(pooled)


def shrunk(table: Mapping[str, Mapping[str, Sequence[float]]],
           margin: Mapping[str, Mapping[str, Sequence[float]]], margin_of: Any,
           overall: Mapping[str, float]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for cond, cells in table.items():
        out[cond] = {}
        for key, (k, n) in cells.items():
            mk, mn = margin[cond].get(margin_of(key), (0.0, 0.0))
            parent = (mk + STRENGTH * overall[cond]) / (mn + STRENGTH)
            out[cond][key] = float((k + STRENGTH * parent) / (n + STRENGTH))
    return out


def prevalence_tables(pooled: Mapping[str, Mapping[str, Sequence[float]]]
                      ) -> tuple[dict[str, dict[str, float]], dict[str, float]]:
    """(prevalence per cell shrunk to its age band x sex margin, overall prevalence) of a
    pooled `{condition: {"age_band|sex|season|region": [cases, persons]}}` table."""
    margin: dict[str, dict[str, list[float]]] = defaultdict(dict)
    for cond, cells in pooled.items():
        for key, (k, n) in cells.items():
            acc = margin[cond].setdefault("|".join(key.split("|")[:2]), [0.0, 0.0])
            acc[0] += k
            acc[1] += n
    overall = {c: sum(k for k, _ in cells.values()) / max(1.0, sum(n for _, n in cells.values()))
               for c, cells in pooled.items()}
    return shrunk(pooled, margin, lambda key: "|".join(key.split("|")[:2]), overall), overall


def percentiles(values: pd.DataFrame, field: str, keys: Sequence[str]) -> dict[str, list[float]]:
    """{cell key: [p05, p50, p95, n]} for cells of at least `MIN_CELL` values."""
    g = values.groupby(list(keys))[field]
    return {"|".join(map(str, k if isinstance(k, tuple) else (k,))):
            [*np.percentile(v.to_numpy(), [5, 50, 95]).tolist(), float(len(v))]
            for k, v in g if len(v) >= MIN_CELL}


def train_priors(model_id: str, version: str, persons: pd.DataFrame,
                 episodes: pd.DataFrame, fields: pd.DataFrame, out: Path) -> Result:
    """`persons`: one row per person; `episodes`: person-month malaria indicators with
    `month`; `fields`: one row per person with field values (e.g. sbp, glucose)."""
    rng = np.random.default_rng(7)
    split = persons.hdt_id.map(split_of)
    full = ["age_band", "sex", "season", "region"]
    rows = persons.assign(season="all")
    conds = [*CONDITIONS]
    month_rows = episodes.merge(persons[["hdt_id", "age_band", "sex", "region"]], on="hdt_id")
    month_rows = month_rows.assign(season=month_rows.month.map(_season))
    train_p, test_p = rows[split == "train"], rows[split == "test"]
    train_m = month_rows[month_rows.hdt_id.map(split_of) == "train"]
    test_m = month_rows[month_rows.hdt_id.map(split_of) == "test"]
    levels = sorted(train_p.facility_level.unique())
    tenants = [train_p[train_p.facility_level == t] for t in levels]
    tables = [count_table(t, full, conds) for t in tenants]
    mtables = [count_table(train_m[train_m.hdt_id.isin(t.hdt_id)], full, [MALARIA])
               for t in tenants]
    result_tables: dict[str, Any] = {}
    briers: dict[str, dict[str, float]] = {}
    for label, eps in (("exact", None), ("dp", EPSILON)):
        pooled = federated_merge(tables, eps, rng) | federated_merge(mtables, eps, rng)
        prior, overall = prevalence_tables(pooled)
        result_tables[label] = {"prevalence": prior, "overall": overall, "counts": pooled}
        briers[label] = {}
        for cond, test in [*((c, test_p) for c in conds), (MALARIA, test_m)]:
            keys = test[full].astype(str).agg("|".join, axis=1)
            p = keys.map(prior[cond]).fillna(overall[cond]).to_numpy(dtype=float)
            y = test[cond].to_numpy(dtype=float)
            briers[label][cond] = float(np.mean((p - y) ** 2))
            briers[label][cond + ".baseline"] = float(np.mean((overall[cond] - y) ** 2))
    norm_keys = ["age_band", "sex"]
    f_train = fields[fields.hdt_id.map(split_of) == "train"]
    f_test = fields[fields.hdt_id.map(split_of) == "test"]
    norms = {f: percentiles(f_train, f, norm_keys) for f in fields.columns
             if f not in ("hdt_id", *ATTRIBUTES)}
    coverage = {}
    inside: dict[str, NDArray[np.bool_]] = {}
    for f, table in norms.items():
        keys = f_test[norm_keys].astype(str).agg("|".join, axis=1)
        lo = keys.map(lambda k, t=table: t.get(k, [np.nan] * 3)[0]).to_numpy(dtype=float)
        hi = keys.map(lambda k, t=table: t.get(k, [np.nan] * 3)[2]).to_numpy(dtype=float)
        ok = (f_test[f].to_numpy() >= lo) & (f_test[f].to_numpy() <= hi)
        coverage[f] = float(ok[np.isfinite(lo)].mean())
        inside[f] = ok
    metrics: dict[str, float] = {}
    for label, b in briers.items():
        for name, v in b.items():
            metrics[f"brier.{label}.{name}"] = v
    for f, v in coverage.items():
        metrics[f"p05_p95_coverage.{f}"] = v
    value = float(np.mean([briers["dp"][c] for c in [*conds, MALARIA]]))
    # Slice table: hypertension prior (MAE against the 0/1 outcome) and the joint p05-p95
    # coverage of the field values, over the test persons with field values.
    cond = conds[0]
    dp = result_tables["dp"]
    sub = test_p.merge(f_test[["hdt_id"]].assign(row=range(len(f_test))), on="hdt_id")
    keys = sub[full].astype(str).agg("|".join, axis=1)
    p_sub = keys.map(lambda k: dp["prevalence"][cond].get(k, dp["overall"][cond])).to_numpy()
    joint = np.all(np.stack([inside[f] for f in norms]), axis=0)[sub.row.to_numpy()]
    report = slice_report(model_id, "regression", sub[cond].to_numpy(dtype=float), p_sub,
                          {a: sub[a].tolist() for a in ATTRIBUTES if a in sub}, covered=joint)
    out.mkdir(parents=True, exist_ok=True)
    (out / "priors.json").write_text(json.dumps(
        {"keys": full, "norm_keys": norm_keys, "strength": STRENGTH, "epsilon": EPSILON,
         "tables": result_tables, "norms": norms}, indent=1), encoding="utf-8")
    result = Result(model_id, version, "atra-synthetic-population (WP02 generator)",
                    "mean_brier_dp", value, metrics, report.to_dict(),
                    split={"tenants": len(tenants), "unit": "person"},
                    notes=["Slice MAE: the differentially private hypertension prior against "
                           "the 0/1 outcome. Slice coverage: all field values inside p05 to p95.",
                           f"Federated update: Laplace noise with epsilon {EPSILON} per tenant "
                           "and cell, numpy implementation."])
    write_result(result, out, fairness_md=report.markdown())
    return result
