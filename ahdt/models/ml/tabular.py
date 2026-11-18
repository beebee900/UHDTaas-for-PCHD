"""Gradient-boosted (LightGBM) binary risk models with conformal sets, operating points,
fairness slices and optional ONNX export for the edge.

Used by the synthetic tasks on the laptop and by the WESAD stress job on the VM, so it
imports only numpy, pandas, LightGBM and the shared T1 helpers.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from sklearn.metrics import brier_score_loss, roc_auc_score

from ahdt.models.ml import conformal
from ahdt.models.ml.artifacts import Result, write_result
from ahdt.models.ml.common import operating_point, sensitivity_specificity, split_masks
from evaluation.models.ahdt.fairness import ATTRIBUTES, ece, slice_report

LEVEL = 0.9
MODEL_FILE = "model.txt"
META_FILE = "model.json"


@dataclass
class EdgeExport:
    """Export the model to `<name>.onnx` + `<name>.json` (edge/inference.py spec)."""

    name: str
    labels: tuple[str, str]
    urgency: str = "urgent"
    rule: tuple[str, float] | None = None
    """(feature, threshold): the probability is 1 when the feature is below the threshold."""


@dataclass
class TabularTask:
    model_id: str
    version: str
    dataset: str
    features: Sequence[str]
    label: str = "label"
    group: str = "hdt_id"
    params: Mapping[str, Any] = field(default_factory=dict)
    min_sensitivity: float = 0.9
    edge: EdgeExport | None = None
    notes: Sequence[str] = ()


DEFAULT_PARAMS: Mapping[str, Any] = {
    "n_estimators": 300, "learning_rate": 0.05, "num_leaves": 15, "min_child_samples": 20,
    "subsample": 0.8, "subsample_freq": 1, "colsample_bytree": 0.9, "n_jobs": 1,
    "verbose": -1, "random_state": 7}


def rule_probability(df: pd.DataFrame, rule: tuple[str, float] | None,
                     p: NDArray[np.float64]) -> NDArray[np.float64]:
    if rule is None:
        return p
    feature, threshold = rule
    out: NDArray[np.float64] = np.maximum(p, (df[feature].to_numpy() < threshold).astype(float))
    return out


def train(task: TabularTask, df: pd.DataFrame, out: Path) -> Result:
    import lightgbm as lgb

    masks = split_masks(df[task.group].astype(str))
    x = df[list(task.features)].to_numpy(dtype=np.float32)
    y = df[task.label].to_numpy(dtype=int)
    model = lgb.LGBMClassifier(**{**DEFAULT_PARAMS, **task.params})
    model.fit(x[masks["train"]], y[masks["train"]])
    rule = task.edge.rule if task.edge else None

    def proba(mask: NDArray[np.bool_]) -> NDArray[np.float64]:
        p = np.asarray(model.predict_proba(x[mask]))[:, 1]
        return rule_probability(df[mask], rule, p)

    p_cal, p_test = proba(masks["cal"]), proba(masks["test"])
    y_cal, y_test = y[masks["cal"]], y[masks["test"]]
    two_cal = np.column_stack([1 - p_cal, p_cal])
    two_test = np.column_stack([1 - p_test, p_test])
    q = conformal.classification_threshold(y_cal, two_cal, LEVEL)
    sets = conformal.prediction_sets(two_test, q)
    covered = conformal.set_covers(sets, y_test)
    threshold = operating_point(y_cal, p_cal, min_sensitivity=task.min_sensitivity)
    sens, spec = sensitivity_specificity(y_test, p_test, threshold)
    auroc = float(roc_auc_score(y_test, p_test))
    metrics = {"auroc": auroc, "brier": float(brier_score_loss(y_test, p_test)),
               "ece": ece(y_test, p_test), "coverage_90": float(covered.mean()),
               "mean_set_size": float(sets.sum(axis=1).mean()),
               "operating_threshold": threshold, "sensitivity": sens, "specificity": spec,
               "prevalence_test": float(y_test.mean())}
    test = df[masks["test"]]
    groups = {a: test[a].tolist() for a in ATTRIBUTES if a in test}
    report = slice_report(task.model_id, "binary", y_test, p_test, groups, covered=covered)
    out.mkdir(parents=True, exist_ok=True)
    model.booster_.save_model(str(out / MODEL_FILE))
    meta = {"features": list(task.features), "rule": list(rule) if rule else None,
            "conformal_threshold": q, "level": LEVEL, "operating_threshold": threshold}
    (out / META_FILE).write_text(json.dumps(meta, indent=1), encoding="utf-8")
    edge_specs: list[Mapping[str, Any]] = []
    if task.edge is not None:
        edge_specs.append(export_onnx(model, task, out, threshold))
    result = Result(task.model_id, task.version, task.dataset, "auroc", auroc, metrics,
                    report.to_dict(),
                    split={k: int(v.sum()) for k, v in masks.items()} | {"unit": task.group},
                    notes=list(task.notes), edge=edge_specs)
    write_result(result, out, fairness_md=report.markdown())
    return result


class Predictor:
    """Runtime form of a trained tabular model: LightGBM booster plus the edge rule."""

    def __init__(self, directory: Path) -> None:
        import lightgbm as lgb

        self.meta = json.loads((directory / META_FILE).read_text(encoding="utf-8"))
        self.booster = lgb.Booster(model_file=str(directory / MODEL_FILE))

    @property
    def features(self) -> list[str]:
        return list(self.meta["features"])

    def probability(self, rows: Sequence[Mapping[str, float]]) -> NDArray[np.float64]:
        df = pd.DataFrame([{f: float(r[f]) for f in self.features} for r in rows])
        p = np.asarray(self.booster.predict(df.to_numpy(dtype=np.float32)), dtype=float)
        rule = tuple(self.meta["rule"]) if self.meta.get("rule") else None
        return rule_probability(df, rule, p)

    def prediction_set(self, p: float) -> list[int]:
        q = float(self.meta["conformal_threshold"])
        return [k for k, pk in enumerate((1 - p, p)) if 1 - pk <= q]


def export_onnx(model: Any, task: TabularTask, out: Path, threshold: float) -> dict[str, Any]:
    """ONNX graph `x` [N, F] float32 -> `p` [N, 2] (probability per label)."""
    import onnx
    from onnx import TensorProto, helper
    from onnxmltools import convert_lightgbm
    from onnxmltools.convert.common.data_types import FloatTensorType

    assert task.edge is not None
    n = len(task.features)
    graph_model = convert_lightgbm(model, initial_types=[("x", FloatTensorType([None, n]))],
                                   zipmap=False, target_opset=15)
    default = [o for o in graph_model.opset_import if o.domain in ("", "ai.onnx")]
    if default:
        default[0].version = max(default[0].version, 15)
    else:
        graph_model.opset_import.extend([helper.make_opsetid("", 15)])
    g = graph_model.graph
    prob_name = next(o.name for o in g.output if o.name != "label")
    nodes = []
    pos = "p_pos"
    nodes.append(helper.make_node("Slice", [prob_name, "c_one", "c_two", "c_one"], [pos]))
    inits = [helper.make_tensor("c_one", TensorProto.INT64, [1], [1]),
             helper.make_tensor("c_two", TensorProto.INT64, [1], [2]),
             helper.make_tensor("c_ones", TensorProto.FLOAT, [1], [1.0])]
    if task.edge.rule is not None:
        feature, value = task.edge.rule
        idx = list(task.features).index(feature)
        inits += [helper.make_tensor("c_idx", TensorProto.INT64, [1], [idx]),
                  helper.make_tensor("c_idx1", TensorProto.INT64, [1], [idx + 1]),
                  helper.make_tensor("c_rule", TensorProto.FLOAT, [1], [float(value)])]
        nodes += [helper.make_node("Slice", ["x", "c_idx", "c_idx1", "c_one"], ["rule_x"]),
                  helper.make_node("Less", ["rule_x", "c_rule"], ["rule_b"]),
                  helper.make_node("Cast", ["rule_b"], ["rule_f"], to=TensorProto.FLOAT),
                  helper.make_node("Max", [pos, "rule_f"], ["p_pos_rule"])]
        pos = "p_pos_rule"
    nodes += [helper.make_node("Sub", ["c_ones", pos], ["p_neg"]),
              helper.make_node("Concat", ["p_neg", pos], ["p"], axis=1)]
    g.node.extend(nodes)
    g.initializer.extend(inits)
    del g.output[:]
    g.output.extend([helper.make_tensor_value_info("p", TensorProto.FLOAT, [None, 2])])
    onnx.checker.check_model(graph_model)
    name = task.edge.name
    onnx.save(graph_model, str(out / f"{name}.onnx"))
    spec = {"model_id": task.model_id, "version": task.version, "file": f"{name}.onnx",
            "input": {"name": "x", "kind": "features", "features": list(task.features)},
            "output": {"name": "p", "labels": list(task.edge.labels)},
            "alert": {"label": task.edge.labels[1], "min_probability": round(threshold, 6),
                      "urgency": task.edge.urgency}}
    (out / f"{name}.json").write_text(json.dumps(spec, indent=1), encoding="utf-8")
    return spec
