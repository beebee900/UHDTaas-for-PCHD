import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from ahdt.models.ml import forecast, gnn, hmm, tabular
from ahdt.models.ml.artifacts import REPORT, Result, check_files, read_metrics
from ahdt.models.ml.common import split_masks
from ahdt.models.ml.inventory import BY_ID, ITEMS, inventory_t1_ids
from ahdt.models.ml.survival import Predictor as SurvivalPredictor
from evaluation.models.ahdt import train as tasks
from evaluation.models.ahdt.fairness import FairnessReport
from synth import training as synthetic

type Trained = tuple[Path, dict[str, Result]]


def test_every_laptop_item_has_a_trainer() -> None:
    laptop = {i.spec.model_id for i in ITEMS if i.runs_on == "laptop"}
    assert laptop == set(tasks.TRAINERS)
    assert all(BY_ID[m].spec.source for m in tasks.TRAINERS)
    assert len(inventory_t1_ids()) == 16


@pytest.mark.parametrize("model_id", list(tasks.TRAINERS))
def test_trainer_writes_validated_artifact(trained: Trained, model_id: str) -> None:
    root, results = trained
    d = root / model_id
    m = read_metrics(d)
    assert m is not None and m["model_id"] == model_id
    assert m["version"] == BY_ID[model_id].spec.version
    v = m["validation"]
    assert v["metric"] == results[model_id].metric and math.isfinite(v["value"])
    assert m["files"] and check_files(d, m) == []
    report = FairnessReport.from_dict(m["fairness"])
    assert report.model_id == model_id and report.rows
    assert "### Fairness slices" in (d / REPORT).read_text()


def test_tabular_predictor_reproduces_rule(trained: Trained) -> None:
    root, _ = trained
    p = tabular.Predictor(root / "ahdt.respiratory.spo2_desaturation_detection")
    row = dict.fromkeys(p.features, 97.0) | {"spo2.n": 30.0, "heart_rate.mean": 90.0,
                                             "heart_rate.max": 100.0}
    feature, threshold = p.meta["rule"]
    low = row | {feature: threshold - 5.0}
    assert p.probability([low])[0] == pytest.approx(1.0)
    assert 0.0 <= p.probability([row])[0] <= 1.0
    q = float(p.meta["conformal_threshold"])
    assert p.prediction_set(0.999) == [k for k, pk in enumerate((0.001, 0.999))
                                       if 1 - pk <= q]
    assert p.prediction_set(1.0) == [1] and p.prediction_set(0.0) == [0]


def test_forecast_predictor_bands(trained: Trained, pop: tasks.Population) -> None:
    root, _ = trained
    p = forecast.Predictor(root / "ahdt.endocrine.glucose_forecasting")
    h, horizon = int(p.meta["history"]), int(p.meta["horizon"])
    series = synthetic.glucose(pop[0]).sort_values("t")
    history = series[series.hdt_id == series.hdt_id.iloc[0]]["glucose"].to_numpy()[:h]
    out = p.forecast(history)
    assert out["mean"].shape == (horizon, 1)
    assert np.all(out["lower"] <= out["mean"]) and np.all(out["mean"] <= out["upper"])
    with pytest.raises(ValueError):
        p.forecast(history[: h - 1])


def test_hmm_models_load(trained: Trained) -> None:
    root, _ = trained
    model, extra = hmm.load(root / "ahdt.whole_body.clinical_health_state" / "model.json")
    assert isinstance(model, hmm.CategoricalHmm) and extra["news2_bands"]
    obs = np.zeros((4, 3), dtype=np.int64)
    alpha, _ = model.posteriors(obs)
    np.testing.assert_allclose(alpha.sum(axis=1), 1.0)
    mh, _ = hmm.load(root / "ahdt.behavioural_cognitive.mental_health_trajectory" / "model.json")
    assert isinstance(mh, hmm.GaussianHmm)


def test_survival_predictor_matches_lifelines(trained: Trained, pop: tasks.Population) -> None:
    from lifelines import CoxPHFitter

    root, _ = trained
    p = SurvivalPredictor(root / "ahdt.behavioural_cognitive.adherence")
    covs = p.p["covariates"]
    df = synthetic.adherence(pop[0])
    masks = split_masks(df.hdt_id.astype(str))
    cph = CoxPHFitter(penalizer=0.01).fit(df.loc[masks["train"], [*covs, "duration_d", "event"]],
                                          duration_col="duration_d", event_col="event")
    rows = df.loc[masks["test"], covs].head(5)
    times = [17.5, 90.0, p.p["horizon_d"]]
    expected = 1.0 - cph.predict_survival_function(rows, times=times).to_numpy()
    got = np.asarray([[p.gap_probability(r, t) for r in rows.to_dict("records")]
                      for t in times])
    np.testing.assert_allclose(got, expected, rtol=1e-6, atol=1e-9)


def test_gnn_predictor(trained: Trained, pop: tasks.Population) -> None:
    root, _ = trained
    df, graph = synthetic.social(*pop)
    p = gnn.Predictor(root / "ahdt.social.social_network").probabilities(df, graph)
    assert set(p) == set(df.hdt_id.astype(str))
    assert all(0.0 <= v <= 1.0 for v in p.values())


def test_population_priors_dp_and_norms(trained: Trained) -> None:
    root, _ = trained
    m = read_metrics(root / "ahdt.population.population_priors_and_norms")
    assert m is not None
    assert any(k.startswith("brier.dp.") for k in m["metrics"])
    assert any(k.startswith("p05_p95_coverage.") for k in m["metrics"])


def test_deterioration_table_window() -> None:
    table = tasks.deterioration_table(tasks._ward(synthetic.population(30)), 6)
    assert {"hdt_id", "label"} <= set(table.columns)
    assert set(pd.unique(table.label)) <= {0, 1}
