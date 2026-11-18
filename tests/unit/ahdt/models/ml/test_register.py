import json
import shutil
from pathlib import Path
from typing import Any

from ahdt.models.ml.__main__ import main
from ahdt.models.ml.inventory import ITEMS
from ahdt.models.ml.register import flat_metrics, register
from atra.backends.memory import FileModelRegistry
from evaluation.models.ahdt.train import TRAINERS


async def test_register_without_artifacts(tmp_path: Path) -> None:
    backend = FileModelRegistry(tmp_path / "registry.json")
    status = await register(backend, root=tmp_path / "t1", edge_dir=tmp_path / "edge",
                            cards_dir=tmp_path / "cards")
    assert [s.model_id for s in status] == [i.spec.model_id for i in ITEMS]
    assert {s.state for s in status} == {"not trained"}
    assert not (tmp_path / "edge").exists()
    card = (tmp_path / "cards" / f"{ITEMS[0].spec.model_id}.md").read_text()
    assert "| Validation | not trained yet |" in card


async def test_register_with_artifacts(trained: tuple[Path, Any], tmp_path: Path) -> None:
    src, _ = trained
    root = tmp_path / "t1"
    shutil.copytree(src, root)
    tampered = "ahdt.behavioural_cognitive.adherence"
    (root / tampered / "model.json").write_text("{}")
    backend = FileModelRegistry(tmp_path / "registry.json")
    status = {s.model_id: s for s in await register(
        backend, root=root, edge_dir=tmp_path / "edge", cards_dir=tmp_path / "cards")}
    assert status[tampered].state == "artifact mismatch"
    assert "model.json" in status[tampered].detail
    for model_id in TRAINERS:
        if model_id != tampered:
            assert status[model_id].state == "registered", model_id
            entry = await backend.get(model_id)
            assert entry.validation is not None and entry.validation.metric
    vm = [i.spec.model_id for i in ITEMS if i.runs_on == "vm"]
    assert all(status[m].state == "not trained" for m in vm)
    assert sorted(p.name for p in (tmp_path / "edge").iterdir()) == [
        "fall_risk.json", "fall_risk.onnx", "spo2_desaturation.json", "spo2_desaturation.onnx"]
    assert "edge: spo2_desaturation" in status["ahdt.respiratory.spo2_desaturation_detection"
                                                ].detail
    card = (tmp_path / "cards" / "ahdt.respiratory.spo2_desaturation_detection.md").read_text()
    assert "## Validation report" in card and "### Fairness slices" in card
    data = json.loads((tmp_path / "registry.json").read_text())
    metrics = data["ahdt.respiratory.spo2_desaturation_detection"]["1.0.0"]["metrics"]
    assert "auroc" in metrics and "fairness.flags" in metrics


def test_flat_metrics() -> None:
    m = {"metrics": {"auroc": 0.9},
         "fairness": {"disparity": {"sex": {"auroc": 0.02}}, "flags": ["x"]}}
    assert flat_metrics(m) == {"auroc": 0.9, "fairness.sex.auroc_disparity": 0.02,
                               "fairness.flags": 1.0}
    assert flat_metrics({})["fairness.flags"] == 0.0


def test_cli_list(trained: tuple[Path, Any], capsys: Any) -> None:
    root, _ = trained
    assert main(["list", "--root", str(root)]) == 0
    out = capsys.readouterr().out
    assert "ahdt.respiratory.spo2_desaturation_detection" in out and "auroc=" in out
    assert "not trained" in out
