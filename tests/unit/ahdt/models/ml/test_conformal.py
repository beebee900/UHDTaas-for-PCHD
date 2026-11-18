import numpy as np
import pytest
from mapie.classification import SplitConformalClassifier
from mapie.regression import SplitConformalRegressor
from sklearn.linear_model import LinearRegression, LogisticRegression

from ahdt.models.ml import conformal

LEVEL = 0.9


def test_quantile_finite_sample() -> None:
    scores = np.arange(1, 11, dtype=float)
    # ceil(11 * 0.9) = 10 -> the 10th smallest score.
    assert conformal.quantile(scores, 0.9) == 10.0
    assert conformal.quantile(scores, 0.5) == 6.0
    assert conformal.quantile(scores[:5], 0.9) == float("inf")
    with pytest.raises(ValueError):
        conformal.quantile([], 0.9)


def test_regression_matches_mapie() -> None:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(600, 3))
    y = x @ [1.0, -2.0, 0.5] + rng.normal(scale=0.7, size=600)
    model = LinearRegression().fit(x[:300], y[:300])
    x_cal, y_cal, x_test = x[300:450], y[300:450], x[450:]
    half = conformal.regression_halfwidth(y_cal, model.predict(x_cal), LEVEL)
    mapie = SplitConformalRegressor(model, confidence_level=LEVEL, prefit=True)
    mapie.conformalize(x_cal, y_cal)
    pred, pis = mapie.predict_interval(x_test)
    np.testing.assert_allclose(pis[:, 0, 0], pred - half, rtol=1e-9)
    np.testing.assert_allclose(pis[:, 1, 0], pred + half, rtol=1e-9)
    covered = conformal.interval_covers(y[450:], pred, half)
    assert covered.mean() > 0.8


def test_classification_matches_mapie() -> None:
    rng = np.random.default_rng(4)
    x = rng.normal(size=(900, 4))
    y = (x[:, 0] + 0.5 * x[:, 1] + rng.normal(scale=0.8, size=900) > 0).astype(int)
    y[x[:, 2] > 1.0] = 2
    model = LogisticRegression(max_iter=500).fit(x[:400], y[:400])
    x_cal, y_cal, x_test = x[400:650], y[400:650], x[650:]
    q = conformal.classification_threshold(y_cal, model.predict_proba(x_cal), LEVEL)
    sets = conformal.prediction_sets(model.predict_proba(x_test), q)
    mapie = SplitConformalClassifier(model, confidence_level=LEVEL, conformity_score="lac",
                                     prefit=True)
    mapie.conformalize(x_cal, y_cal)
    _, mapie_sets = mapie.predict_set(x_test)
    np.testing.assert_array_equal(sets, mapie_sets[:, :, 0])
    assert conformal.set_covers(sets, y[650:]).mean() > 0.8
