"""The edge models against the edge spec of `edge/inference.py` (WP11)."""

import json
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import numpy as np
import onnxruntime as ort
import pytest

from ahdt.ingest.fields import field_index
from ahdt.models.ml import tabular
from ahdt.models.ml.common import split_masks
from ahdt.models.ml.register import EDGE_DIR
from synth import training as synthetic
from tests.unit.ahdt.models.ml.conftest import LARGER

EDGE = {"ahdt.respiratory.spo2_desaturation_detection": ("spo2_desaturation",
                                                          synthetic.desaturation),
        "ahdt.musculoskeletal.gait_and_fall_risk": ("fall_risk", synthetic.falls)}
STATS = ("mean", "min", "max", "n")


def check_spec(spec: Mapping[str, Any], directory: Path) -> ort.InferenceSession:
    """The edge spec contract of edge/inference.py, checked against the ONNX file."""
    assert {"model_id", "version", "file", "input", "output"} <= set(spec)
    inp, out = spec["input"], spec["output"]
    session = ort.InferenceSession(str(directory / spec["file"]),
                                   providers=["CPUExecutionProvider"])
    inputs = {i.name: i for i in session.get_inputs()}
    assert inp["name"] in inputs
    assert out["name"] in {o.name for o in session.get_outputs()} and out["labels"]
    index = field_index()
    if inp["kind"] == "features":
        assert len(inputs[inp["name"]].shape) == 2
        for f in inp["features"]:
            name, stat = f.rsplit(".", 1)
            assert stat in STATS and index.by_name(name) is not None, f
    else:
        assert inp["kind"] == "waveform"
        assert index.by_name(inp["field"]) is not None
        assert inp["fs"] > 0 and inp["samples"] > 0
    if "alert" in spec:
        a = spec["alert"]
        assert a["label"] in out["labels"] and 0 <= a["min_probability"] <= 1
        assert a["urgency"] in ("emergency", "urgent", "routine")
    return session


@pytest.mark.parametrize("model_id", list(EDGE))
def test_onnx_matches_lightgbm(trained: tuple[Path, Any], pop: Any, model_id: str) -> None:
    root, _ = trained
    d = root / model_id
    name, make = EDGE[model_id]
    spec = json.loads((d / f"{name}.json").read_text())
    session = check_spec(spec, d)
    predictor = tabular.Predictor(d)
    assert spec["input"]["features"] == predictor.features
    persons = synthetic.population(400)[0] if model_id in LARGER else pop[0]
    df = make(persons)
    rows = df[split_masks(df.hdt_id.astype(str))["test"]][predictor.features].head(200)
    x = rows.to_numpy(dtype=np.float32)
    (p,) = session.run([spec["output"]["name"]], {spec["input"]["name"]: x})
    want = predictor.probability(rows.to_dict("records"))
    np.testing.assert_allclose(p[:, 1], want, atol=1e-5)
    np.testing.assert_allclose(p.sum(axis=1), 1.0, atol=1e-6)


def test_edge_models_load_in_onnx_host(trained: tuple[Path, Any], tmp_path: Path) -> None:
    inference = pytest.importorskip("edge.inference", reason="edge/inference.py comes with WP11")
    root, _ = trained
    for model_id, (name, _) in EDGE.items():
        for suffix in (".onnx", ".json"):
            shutil.copy2(root / model_id / f"{name}{suffix}", tmp_path / f"{name}{suffix}")
    host = inference.OnnxHost.from_dir(tmp_path)
    assert set(host.models) == set(EDGE)
    m = host.models["ahdt.respiratory.spo2_desaturation_detection"]
    probs = m.run([90.0] * len(m.spec.input.features))
    assert set(probs) == {"normal", "desaturation"}


def test_installed_arrhythmia_model() -> None:
    path = EDGE_DIR / "arrhythmia.json"
    if not path.exists():
        pytest.skip("arrhythmia.onnx is installed by register after the VM job")
    spec = json.loads(path.read_text())
    session = check_spec(spec, EDGE_DIR)
    x = np.zeros((1, 1, spec["input"]["samples"]), dtype=np.float32)
    rank = len(session.get_inputs()[0].shape)
    (p,) = session.run(["p"], {"x": x.reshape((1,) * (rank - 1) + (-1,))})
    assert p.shape == (1, len(spec["output"]["labels"]))
    np.testing.assert_allclose(p.sum(), 1.0, atol=1e-5)
