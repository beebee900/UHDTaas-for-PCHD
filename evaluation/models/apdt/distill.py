"""Distil the value-of-information test policy into a decision tree.

    python -m evaluation.models.apdt.distill [--cases N] [--root DIR]

The teacher is `rank_tests` (its top-scoring test) on synthetic cohort cases. The student is a
scikit-learn decision tree on the encoded evidence. Fidelity is the agreement on held-out
cases. Run it through `var/bin/heavy`.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from sklearn.tree import DecisionTreeClassifier

from ahdt.models.ml.artifacts import Result, write_result
from ahdt.models.ml.common import split_of
from apdt.models.diagnosis.bn import DifferentialModel, build_network
from apdt.models.diagnosis.comparator import APDT_ROOT, feature_names
from apdt.models.diagnosis.distilled import FILE, MODEL_ID, encode
from apdt.models.diagnosis.tests_select import rank_tests
from evaluation.models.apdt.cohort import Case, generate_cohort

DATASET = "atra-synthetic-diagnostic-cohort (evaluation/models/apdt/cohort.py)"
NO_TEST = "none"


def teacher(model: DifferentialModel, case: Case) -> str:
    scores, _ = rank_tests(model, case.patient, case.observations)
    return scores[0].test_id if scores and scores[0].voi > 0 else NO_TEST


def distill(cases: Sequence[Case], root: Path, *, max_depth: int = 6) -> Result:
    model = DifferentialModel()
    x = np.vstack([encode(c.patient, c.observations) for c in cases])
    y = np.asarray([teacher(model, c) for c in cases])
    train = np.asarray([split_of(c.key, "distill") != "test" for c in cases])
    classes = sorted(set(y))
    labels = np.asarray([classes.index(v) for v in y])
    tree = DecisionTreeClassifier(max_depth=max_depth, min_samples_leaf=5, random_state=0
                                  ).fit(x[train], labels[train])
    fidelity = float((tree.predict(x[~train]) == labels[~train]).mean())
    majority = float(np.mean(labels[~train] == np.bincount(labels[train]).argmax()))
    t = tree.tree_
    spec = {"classes": [classes[i] for i in tree.classes_], "features": feature_names(
        build_network()), "tree": {
            "left": t.children_left.tolist(), "right": t.children_right.tolist(),
            "feature": t.feature.tolist(), "threshold": t.threshold.tolist(),
            "value": t.value[:, 0, :].argmax(axis=1).tolist()}}
    out = root / MODEL_ID
    out.mkdir(parents=True, exist_ok=True)
    (out / FILE).write_text(json.dumps(spec), encoding="utf-8")
    result = Result(MODEL_ID, "1.0.0", DATASET, "fidelity", fidelity,
                    {"fidelity": fidelity, "majority_baseline": majority,
                     "depth": float(tree.get_depth()), "leaves": float(tree.get_n_leaves())},
                    None, {"train": int(train.sum()), "test": int((~train).sum())},
                    ["Teacher: the top-scoring test of apdt.diagnosis.test_selection."])
    write_result(result, out)
    return result


def main(argv: Sequence[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="python -m evaluation.models.apdt.distill")
    parser.add_argument("--cases", type=int, default=600)
    parser.add_argument("--root", type=Path, default=APDT_ROOT)
    args = parser.parse_args(argv)
    r = distill(generate_cohort(args.cases, 13), args.root)
    print(f"{MODEL_ID}: fidelity = {r.value:.3f}; " + ", ".join(
        f"{k}={v:.3g}" for k, v in r.metrics.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
