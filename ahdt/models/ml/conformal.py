"""Split conformal prediction for the T1 models (design 01: MAPIE 1.5 semantics).

Regression uses the absolute-residual score and classification the LAC score
(1 - probability of the true class), with the finite-sample quantile
ceil((n + 1) * level) / n of the calibration scores. These are the defaults of MAPIE's
`SplitConformalRegressor` and `SplitConformalClassifier`; the test suite checks that both
give the same bands. The numpy form also serves models MAPIE cannot wrap (Darts
forecasters, HMMs, torch networks on the VM) and stores as one number per output.
"""

from __future__ import annotations

import math

import numpy as np
from numpy.typing import ArrayLike, NDArray


def quantile(scores: ArrayLike, level: float) -> float:
    s = np.sort(np.asarray(scores, dtype=float).ravel())
    n = s.size
    if n == 0:
        raise ValueError("no calibration scores")
    k = math.ceil((n + 1) * level)
    return float("inf") if k > n else float(s[k - 1])


def regression_halfwidth(y_cal: ArrayLike, pred_cal: ArrayLike, level: float = 0.9) -> float:
    return quantile(np.abs(np.asarray(y_cal, dtype=float) - np.asarray(pred_cal, dtype=float)),
                    level)


def classification_threshold(y_cal: ArrayLike, proba_cal: ArrayLike,
                             level: float = 0.9) -> float:
    p = np.asarray(proba_cal, dtype=float)
    y = np.asarray(y_cal, dtype=int)
    return quantile(1.0 - p[np.arange(len(y)), y], level)


def prediction_sets(proba: ArrayLike, threshold: float) -> NDArray[np.bool_]:
    """Boolean (n, k): class k is in the set when 1 - p_k <= threshold."""
    out: NDArray[np.bool_] = (1.0 - np.asarray(proba, dtype=float)) <= threshold
    return out


def set_covers(sets: NDArray[np.bool_], y: ArrayLike) -> NDArray[np.bool_]:
    yy = np.asarray(y, dtype=int)
    covered: NDArray[np.bool_] = sets[np.arange(len(yy)), yy]
    return covered


def interval_covers(y: ArrayLike, pred: ArrayLike, halfwidth: ArrayLike) -> NDArray[np.bool_]:
    covered: NDArray[np.bool_] = np.abs(np.asarray(y, dtype=float)
                                        - np.asarray(pred, dtype=float)) <= np.asarray(halfwidth)
    return covered
