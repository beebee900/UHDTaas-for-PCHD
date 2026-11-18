"""ONNX Runtime host for the edge models, on tiny models built with `onnx.helper`."""

import json
from datetime import timedelta

import numpy as np
import onnx
import pytest
from onnx import TensorProto, helper, numpy_helper

from edge.devices.decode.observations import HEART_RATE, SPO2
from edge.inference import EdgeModel, EdgeModelSpec, OnnxHost
from edge.preprocess import ECG_CODE, Preprocessor
from tests.unit.edge.service.support import HDT, START
from tests.unit.edge.service.test_preprocess import reading

MDC = "urn:iso:std:iso:11073:10101"


def linear_softmax(weights, bias, *, shape, flatten=False):
    """`softmax(x @ W + b)`; with `flatten`, x of rank 3 is flattened first."""
    w = numpy_helper.from_array(np.asarray(weights, dtype=np.float32), "W")
    b = numpy_helper.from_array(np.asarray(bias, dtype=np.float32), "B")
    nodes = []
    source = "x"
    if flatten:
        nodes.append(helper.make_node("Flatten", ["x"], ["flat"], axis=1))
        source = "flat"
    nodes += [helper.make_node("MatMul", [source, "W"], ["xw"]),
              helper.make_node("Add", ["xw", "B"], ["logits"]),
              helper.make_node("Softmax", ["logits"], ["p"], axis=-1)]
    graph = helper.make_graph(
        nodes, "edge-test", [helper.make_tensor_value_info("x", TensorProto.FLOAT, shape)],
        [helper.make_tensor_value_info("p", TensorProto.FLOAT, [1, len(bias)])], [w, b])
    model = helper.make_model(graph, opset_imports=[helper.make_opsetid("", 17)])
    model.ir_version = 9
    onnx.checker.check_model(model)
    return model.SerializeToString()


DESAT = {"model_id": "ahdt.respiratory.desaturation_detection", "version": "1.0.0",
         "file": "desaturation.onnx",
         "input": {"name": "x", "kind": "features",
                   "features": ["spo2.mean", "spo2.min", "heart_rate.mean"]},
         "output": {"name": "p", "labels": ["normal", "desaturation"]},
         "alert": {"label": "desaturation", "min_probability": 0.5, "urgency": "urgent"}}


def desaturation_model():
    # The desaturation logit rises 1 per SpO2 point below 92 of the window minimum.
    return linear_softmax([[0.0, 0.0], [0.0, -1.0], [0.0, 0.0]], [0.0, 92.0], shape=[1, 3])


def windows(spo2_values, hr=80):
    pre = Preprocessor(window_s=60.0)
    payloads = [reading(SPO2, v, "%", START + timedelta(seconds=5 * i))
                for i, v in enumerate(spo2_values)]
    payloads += [reading(HEART_RATE, hr, "/min", START + timedelta(seconds=5 * i))
                 for i in range(len(spo2_values))]
    return pre.process(payloads, START + timedelta(minutes=1)).features


def test_feature_model_detects_desaturation_on_closed_windows():
    host = OnnxHost([EdgeModel(EdgeModelSpec.model_validate(DESAT), desaturation_model())])
    (normal,) = host.on_features(windows([97, 96, 98]))
    assert not normal.fires
    assert normal.probabilities["normal"] == pytest.approx(1 / (1 + np.exp(-4)))
    (low,) = host.on_features(windows([94, 87, 90]))
    assert low.fires and low.hdt_id == HDT and low.time == START
    assert sum(low.probabilities.values()) == pytest.approx(1.0, abs=1e-6)
    assert low.probabilities["desaturation"] == pytest.approx(1 / (1 + np.exp(-5)), rel=1e-5)
    # A window without every input feature is skipped.
    only_hr = Preprocessor().process(
        [reading(HEART_RATE, 70, "/min", START)], START + timedelta(minutes=1)).features
    assert host.on_features(only_hr) == []


def test_waveform_model_reads_the_last_samples_at_its_rate():
    n = 8
    spec = EdgeModelSpec.model_validate({
        "model_id": "ahdt.cardiovascular.arrhythmia", "version": "0.1.0", "file": "a.onnx",
        "input": {"name": "x", "kind": "waveform", "field": "ecg_lead_ii", "fs": 250,
                  "samples": n},
        "output": {"name": "p", "labels": ["sinus", "irregular"]}})
    weights = np.zeros((n, 2))
    weights[-1, 1] = 10.0
    model = EdgeModel(spec, linear_softmax(weights, [0.0, 0.0], shape=[1, 1, n],
                                           flatten=True))
    host = OnnxHost([model])
    wave = reading(ECG_CODE, {"array": [0.0] * 20 + [1.0], "period_ms": 4.0}, "mV", START,
                   system=MDC)
    (d,) = host.on_waveforms([wave])
    assert d.probabilities["irregular"] == pytest.approx(1 / (1 + np.exp(-10)), rel=1e-5)
    assert not d.fires
    short = {**wave, "value": {"array": [0.0] * (n - 1), "period_ms": 4.0}}
    other_rate = {**wave, "value": {"array": [0.0] * 20, "period_ms": 2.0}}
    assert host.on_waveforms([short, other_rate]) == []


def test_models_load_from_a_directory_and_bad_specs_are_refused(tmp_path):
    (tmp_path / "desaturation.onnx").write_bytes(desaturation_model())
    (tmp_path / "desaturation.json").write_text(json.dumps(DESAT))
    host = OnnxHost.from_dir(tmp_path)
    assert list(host.models) == [DESAT["model_id"]]
    assert OnnxHost.from_dir(tmp_path / "missing").models == {}

    bad_input = EdgeModelSpec.model_validate({**DESAT, "input": {**DESAT["input"],
                                                                  "name": "y"}})
    with pytest.raises(ValueError, match="no input y"):
        EdgeModel(bad_input, desaturation_model())
    bad_alert = EdgeModelSpec.model_validate({**DESAT, "alert": {**DESAT["alert"],
                                                                  "label": "apnoea"}})
    with pytest.raises(ValueError, match="not an output"):
        EdgeModel(bad_alert, desaturation_model())
    three = EdgeModelSpec.model_validate({**DESAT, "alert": None, "output": {
        "name": "p", "labels": ["a", "b", "c"]}})
    with pytest.raises(ValueError, match="2 outputs for 3 labels"):
        EdgeModel(three, desaturation_model()).run([95, 90, 70])
