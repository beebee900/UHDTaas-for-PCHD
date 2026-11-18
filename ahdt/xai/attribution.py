"""Explainers for models that score feature rows (design 04, 4.6.1, tabular ML).

SHAP (Tree and Kernel), LIME and the EBM glass-box twin attribute one score to its
features. Partial dependence and permutation importance describe the model on a
reference set. DiCE searches counterfactual rows.

`background` is a reference population or, when the caller has none, a local sample
around the instance. Sample counts are small on purpose: an explanation runs on request.
"""

from __future__ import annotations

import warnings
from typing import Any

import numpy as np

from ahdt.xai.subjects import TabularSubject, reference_set
from ahdt.xai.types import Array, Result, driver, drivers_from
from atra import contracts as c

SHAP_SAMPLES = 120
LIME_SAMPLES = 400
EBM_ROWS = 300
PDP_POINTS = 6
PERMUTATION_REPEATS = 3


def _lib_version(name: str) -> str:
    from importlib.metadata import version

    return version(name)


def shap_tree(s: TabularSubject) -> Result:
    """Exact Shapley values of the LightGBM trees, in log-odds."""
    import shap

    if s.booster is None:
        raise ValueError(f"{s.model_id} has no tree model; use shap.kernel")
    explainer = shap.TreeExplainer(s.booster)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = explainer.shap_values(s.x[None, :])
    values = np.asarray(raw[-1] if isinstance(raw, list) else raw, dtype=float).reshape(-1)
    base = float(np.asarray(explainer.expected_value).reshape(-1)[-1])
    return Result(f"shap.tree@{_lib_version('shap')}", "attribution",
                  drivers_from(s.features, s.x, values), output=s.output,
                  base=float(1.0 / (1.0 + np.exp(-base))),
                  detail={"scale": "log_odds", "base_log_odds": base,
                          "sum": float(values.sum())})


def shap_kernel(s: TabularSubject, samples: int = SHAP_SAMPLES) -> Result:
    """Kernel SHAP of the served score, in probability."""
    import shap

    reference = shap.kmeans(s.background, min(10, len(s.background))).data \
        if len(s.background) > 10 else s.background
    explainer = shap.KernelExplainer(s.predict, reference)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        raw = explainer.shap_values(s.x[None, :], nsamples=samples, silent=True)
    values = np.asarray(raw[-1] if isinstance(raw, list) else raw, dtype=float).reshape(-1)
    return Result(f"shap.kernel@{_lib_version('shap')}", "attribution",
                  drivers_from(s.features, s.x, values), output=s.output,
                  base=float(np.asarray(explainer.expected_value).reshape(-1)[-1]),
                  detail={"scale": "probability", "samples": samples})


def lime_tabular(s: TabularSubject, samples: int = LIME_SAMPLES) -> Result:
    """Local linear surrogate of the score (LIME)."""
    from lime.lime_tabular import LimeTabularExplainer

    explainer = LimeTabularExplainer(
        s.background, feature_names=s.features, mode="classification",
        discretize_continuous=False, random_state=0)

    def proba(rows: Array) -> Array:
        p = s.predict(rows)
        return np.column_stack([1.0 - p, p])

    exp = explainer.explain_instance(s.x, proba, num_features=len(s.features),
                                     num_samples=samples, labels=(1,))
    weights = dict(exp.as_map()[1])
    contributions = [float(weights.get(i, 0.0)) for i in range(len(s.features))]
    return Result(f"lime.tabular@{_lib_version('lime')}", "attribution",
                  drivers_from(s.features, s.x, contributions), output=s.output,
                  detail={"scale": "local_linear_weight", "local_prediction":
                          float(exp.local_pred[0]) if exp.local_pred is not None else None,
                          "samples": samples})


def ebm_twin(s: TabularSubject, rows: int = EBM_ROWS) -> Result:
    """An Explainable Boosting Machine fitted to the served score: a glass-box twin whose
    per-feature terms add up to its own prediction."""
    from interpret.glassbox import ExplainableBoostingRegressor

    rng = np.random.default_rng(1)
    pool = s.background
    idx = rng.integers(0, len(pool), size=max(rows, len(pool)))
    jitter = rng.normal(0.0, 0.05, size=(len(idx), pool.shape[1])) \
        * np.maximum(pool.std(axis=0), 1e-6)
    x_fit = pool[idx] + jitter
    y_fit = s.predict(x_fit)
    ebm = ExplainableBoostingRegressor(
        feature_names=s.features, interactions=0, outer_bags=2, max_rounds=60,
        n_jobs=1, random_state=0)
    ebm.fit(x_fit, y_fit)
    terms = np.asarray(ebm.eval_terms(s.x[None, :]), dtype=float).reshape(-1)
    fit_pred = np.asarray(ebm.predict(x_fit), dtype=float)
    ss_res = float(((y_fit - fit_pred) ** 2).sum())
    ss_tot = float(((y_fit - y_fit.mean()) ** 2).sum())
    fidelity = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    return Result(f"ebm.glassbox@{_lib_version('interpret-core')}", "attribution",
                  drivers_from(s.features, s.x, terms), output=s.output,
                  base=float(ebm.intercept_), fidelity=fidelity,
                  detail={"scale": "probability", "twin_prediction":
                          float(ebm.predict(s.x[None, :])[0]), "fit_rows": len(x_fit)})


def partial_dependence(s: TabularSubject, points: int = PDP_POINTS) -> Result:
    """Average score as one feature moves over its observed range; the driver is the
    average score at the instance's value minus the overall average."""
    overall = float(s.predict(s.background).mean())
    drivers = []
    curves: dict[str, dict[str, list[float]]] = {}
    for j, name in enumerate(s.features):
        grid = np.unique(np.quantile(s.background[:, j], np.linspace(0, 1, points)))
        means = []
        for g in grid:
            rows = s.background.copy()
            rows[:, j] = g
            means.append(float(s.predict(rows).mean()))
        curves[name] = {"grid": [float(g) for g in grid], "mean": means}
        rows = s.background.copy()
        rows[:, j] = s.x[j]
        drivers.append(driver(name, s.x[j], float(s.predict(rows).mean()) - overall))
    return Result("pdp.average@own", "attribution", drivers, output=s.output, base=overall,
                  detail={"curves": curves})


def permutation_importance(s: TabularSubject, repeats: int = PERMUTATION_REPEATS) -> Result:
    """Mean absolute change of the score when one feature is shuffled across the reference
    set. The driver's sign is the effect of replacing the instance's value by the
    reference average."""
    rng = np.random.default_rng(2)
    base = s.predict(s.background)
    importance = []
    for j in range(len(s.features)):
        deltas = []
        for _ in range(repeats):
            rows = s.background.copy()
            rows[:, j] = rng.permutation(rows[:, j])
            deltas.append(float(np.abs(s.predict(rows) - base).mean()))
        importance.append(float(np.mean(deltas)))
    swapped = []
    for j in range(len(s.features)):
        x = s.x.copy()
        x[j] = s.background[:, j].mean()
        swapped.append(s.output - float(s.predict(x[None, :])[0]))
    drivers = drivers_from(s.features, s.x, swapped)
    return Result("permutation.importance@own", "attribution", drivers, output=s.output,
                  detail={"importance": dict(zip(s.features, importance, strict=True)),
                          "repeats": repeats})


class _Wrapper:
    """The scikit-learn estimator interface DiCE expects."""

    def __init__(self, s: TabularSubject) -> None:
        self.s = s
        self.classes_ = np.array([0, 1])

    def predict_proba(self, rows: Any) -> Array:
        p = self.s.predict(np.asarray(rows, dtype=float))
        return np.column_stack([1.0 - p, p])

    def predict(self, rows: Any) -> Array:
        out: Array = (self.predict_proba(rows)[:, 1] >= self.s.threshold).astype(int)
        return out


def dice_counterfactuals(s: TabularSubject, count: int = 2) -> Result:
    """Counterfactual rows that flip the decision, changing only actionable features."""
    import dice_ml
    import pandas as pd

    rng = np.random.default_rng(3)
    pool = np.vstack([s.background, s.x[None, :]])
    pool = np.vstack([pool, pool + rng.normal(0, 0.05, pool.shape)
                      * np.maximum(pool.std(axis=0), 1e-6)])
    frame = pd.DataFrame(pool, columns=s.features)
    wrapper = _Wrapper(s)
    frame["outcome"] = wrapper.predict(pool)
    if frame["outcome"].nunique() < 2:
        return Result("dice.random@" + _lib_version("dice-ml"), "counterfactual",
                      output=s.output, counterfactuals=[],
                      detail={"note": "the reference set has a single decision"})
    data = dice_ml.Data(dataframe=frame, continuous_features=list(s.features),
                        outcome_name="outcome")
    model = dice_ml.Model(model=wrapper, backend="sklearn")
    dice = dice_ml.Dice(data, model, method="random")
    query = pd.DataFrame([s.row()])
    now = int(wrapper.predict(s.x[None, :])[0])
    vary = [f for f in s.features if f in s.actionable]
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        found = dice.generate_counterfactuals(
            query, total_CFs=count, desired_class=1 - now, features_to_vary=vary,
            permitted_range={f: [float(lo), float(hi)] for f, (lo, hi) in s.bounds.items()
                             if f in vary})
    cfs = found.cf_examples_list[0].final_cfs_df
    out: list[c.Counterfactual] = []
    if cfs is not None:
        for _, row in cfs.iterrows():
            changes = {f: float(row[f]) for f in s.features
                       if abs(float(row[f]) - float(s.row()[f])) > 1e-9}
            new = np.array([float(row[f]) for f in s.features])
            out.append(c.Counterfactual(
                changes=changes, outcome=float(s.predict(new[None, :])[0])))
    return Result(f"dice.random@{_lib_version('dice-ml')}", "counterfactual",
                  output=s.output, counterfactuals=out,
                  detail={"desired_class": 1 - now, "requested": count})


def with_reference(s: TabularSubject, n: int = 40) -> TabularSubject:
    """A copy of `s` whose reference set is a local sample around the instance."""
    from dataclasses import replace

    return replace(s, background=reference_set(s.x, n=n))
