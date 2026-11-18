"""Training and validation of the APDT T1 diagnosis models on the synthetic cohort.

    python -m evaluation.models.apdt.train [--cases N] [--root DIR] [--no-weights]

Run it through `var/bin/heavy`. Trains the XGBoost comparator with its split-conformal
threshold, fits the Bayesian-model-averaging weights of the network structure variants by BIC
on the calibration split, and writes the validation and fairness report.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ahdt.models.ml import conformal
from ahdt.models.ml.artifacts import Result, write_result
from ahdt.models.ml.common import split_of
from ahdt.models.ml.slices import bands
from apdt.models.diagnosis import bn
from apdt.models.diagnosis.bn import VARIANTS, DifferentialModel, Enumerator, Evidence
from apdt.models.diagnosis.comparator import (
    APDT_ROOT,
    META_FILE,
    MODEL_FILE,
    MODEL_ID,
    feature_names,
    features,
)
from evaluation.models.ahdt.fairness import slice_report
from evaluation.models.apdt.cohort import NONE, Case, generate_cohort

DATASET = "atra-synthetic-diagnostic-cohort (evaluation/models/apdt/cohort.py)"
LEVEL = 0.9
SALT = "apdt"


def split_cases(cases: Sequence[Case]) -> dict[str, list[Case]]:
    out: dict[str, list[Case]] = {"train": [], "cal": [], "test": []}
    for c in cases:
        out[split_of(c.key, SALT)].append(c)
    return out


def fit_bma_weights(cal: Sequence[Case], model: DifferentialModel | None = None
                    ) -> tuple[dict[str, float], dict[str, Any]]:
    """Weights proportional to exp(-BIC/2) of each structure variant on the calibration cases."""
    model = model or DifferentialModel()
    loglik = dict.fromkeys(VARIANTS, 0.0)
    used = 0
    for case in cal:
        evidence = Evidence.of(case.observations, model.net)
        enum = Enumerator(model.net, {c: v[0] for c, v in model.priors(case.patient).items()},
                          evidence)
        probs = {v: enum.evidence_probability(v) for v in VARIANTS}
        if min(probs.values()) <= 0.0:
            continue
        for v in VARIANTS:
            loglik[v] += math.log(probs[v])
        used += 1
    n = max(used, 1)
    k = sum(len(node.links) for node in model.net.findings.values()) \
        + sum(len(node.links) for node in model.net.tests.values())
    bic = {v: -2.0 * loglik[v] + k * math.log(n) for v in VARIANTS}
    low = min(bic.values())
    raw = {v: math.exp(-(bic[v] - low) / 2.0) for v in VARIANTS}
    total = sum(raw.values())
    weights = {v: raw[v] / total for v in VARIANTS}
    return weights, {"n_cases": used, "loglik": loglik, "bic": bic, "parameters": k,
                     "dataset": DATASET}


def _matrix(cases: Sequence[Case]) -> NDArray[np.float64]:
    return np.vstack([features(c.patient, c.observations) for c in cases])


def _labels(cases: Sequence[Case], classes: list[str]) -> NDArray[np.int64]:
    index = {c: i for i, c in enumerate(classes)}
    return np.asarray([index.get(c.primary, index[NONE]) for c in cases], dtype=np.int64)


def train_comparator(cases: Sequence[Case], out: Path, *, quick: bool = False) -> Result:
    import xgboost as xgb

    parts = split_cases(cases)
    train_c, cal_c, test_c = parts["train"], parts["cal"], parts["test"]
    classes = sorted({c.primary for c in train_c} | {NONE})
    x_tr, y_tr = _matrix(train_c), _labels(train_c, classes)
    present = np.unique(y_tr)
    remap = {int(old): i for i, old in enumerate(present)}
    classes = [classes[int(i)] for i in present]
    y_tr = np.asarray([remap[int(v)] for v in y_tr])
    clf = xgb.XGBClassifier(
        n_estimators=30 if quick else 120, max_depth=4, learning_rate=0.1,
        objective="multi:softprob", tree_method="hist", n_jobs=2, subsample=0.9,
        random_state=0, verbosity=0)
    clf.fit(x_tr, y_tr)

    def encode(group: Sequence[Case]) -> NDArray[np.int64]:
        index = {c: i for i, c in enumerate(classes)}
        return np.asarray([index.get(c.primary, index[NONE]) for c in group], dtype=np.int64)

    p_cal, y_cal = clf.predict_proba(_matrix(cal_c)), encode(cal_c)
    threshold = conformal.classification_threshold(y_cal, p_cal, LEVEL)
    x_te, y_te = _matrix(test_c), encode(test_c)
    p_te = clf.predict_proba(x_te)
    sets = conformal.prediction_sets(p_te, threshold)
    covered = conformal.set_covers(sets, y_te)
    acc = float((p_te.argmax(axis=1) == y_te).mean())

    model = DifferentialModel()
    bn_top = []
    for c in test_c:
        top = model.differential(c.patient, c.observations).top()
        bn_top.append(top.condition if top else NONE)
    bn_acc = float(np.mean([t == c.primary for t, c in zip(bn_top, test_c, strict=True)]))
    agree = float(np.mean([classes[int(a)] == t
                           for a, t in zip(p_te.argmax(axis=1), bn_top, strict=True)]))
    set_size = float(sets.sum(axis=1).mean())

    out.mkdir(parents=True, exist_ok=True)
    clf.save_model(str(out / MODEL_FILE))
    (out / META_FILE).write_text(json.dumps(
        {"classes": classes, "threshold": threshold, "level": LEVEL,
         "features": feature_names(bn.build_network())}, indent=1) + "\n", encoding="utf-8")
    groups = {"sex": [c.patient.sex for c in test_c],
              "age_band": [next((b[0] for b in bands() if b[1] <= c.patient.age_years < b[2]),
                                "unknown") for c in test_c]}
    fair = slice_report(MODEL_ID, "multiclass", y_te, p_te, groups, covered=covered)
    result = Result(
        MODEL_ID, "1.0.0", DATASET, "top1_accuracy", acc,
        {"top1_accuracy": acc, "bn_top1_accuracy": bn_acc, "bn_xgb_agreement": agree,
         "conformal_coverage": float(covered.mean()), "conformal_mean_set_size": set_size,
         "conformal_level": LEVEL},
        fair.to_dict(),
        {"train": len(train_c), "cal": len(cal_c), "test": len(test_c)},
        ["The cohort is generated from the same noisy-OR process as the network, so these "
         "numbers test the implementation and not clinical accuracy.",
         "The label is the true condition that explains the most observed positive items."])
    write_result(result, out, fairness_md=fair.markdown())
    return result


def train(root: Path, *, cases: int = 3000, seed: int = 11, quick: bool = False,
          weights: bool = True) -> dict[str, Result]:
    cohort = generate_cohort(cases, seed)
    results = {MODEL_ID: train_comparator(cohort, root / MODEL_ID, quick=quick)}
    if weights:
        w, info = fit_bma_weights(split_cases(cohort)["cal"])
        bn.write_weights(w, info)
    return results


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m evaluation.models.apdt.train")
    parser.add_argument("--cases", type=int, default=3000)
    parser.add_argument("--root", type=Path, default=APDT_ROOT)
    parser.add_argument("--no-weights", action="store_true")
    args = parser.parse_args(argv)
    for model_id, r in train(args.root, cases=args.cases, weights=not args.no_weights).items():
        print(f"{model_id}: {r.metric} = {r.value:.4g}; "
              + ", ".join(f"{k}={v:.3g}" for k, v in r.metrics.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
