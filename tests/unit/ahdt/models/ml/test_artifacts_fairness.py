import json
from pathlib import Path

import numpy as np
import pytest

from ahdt.models.ml import slices
from ahdt.models.ml.artifacts import (
    METRICS,
    REPORT,
    Result,
    check_files,
    default_root,
    read_metrics,
    write_result,
)
from ahdt.models.ml.common import operating_point, sensitivity_specificity, split_masks, split_of
from evaluation.models.ahdt.fairness import (
    ATTRIBUTES,
    FairnessReport,
    concordance,
    ece,
    slice_report,
)


def test_write_and_read_result(tmp_path: Path) -> None:
    (tmp_path / "model.txt").write_text("weights")
    result = Result("m.x", "1.0.0", "ds", "auroc", 0.81, {"auroc": 0.81, "brier": 0.1},
                    split={"train": 6, "unit": "person"}, notes=["a note"],
                    edge=[{"file": "m.onnx"}])
    write_result(result, tmp_path, fairness_md="### Fairness slices: m.x")
    m = read_metrics(tmp_path)
    assert m is not None
    assert m["validation"]["metric"] == "auroc" and m["validation"]["value"] == 0.81
    assert set(m["files"]) == {"model.txt"}
    assert m["edge"] == [{"file": "m.onnx"}]
    report = (tmp_path / REPORT).read_text()
    assert "| auroc | 0.81 |" in report and "- a note" in report
    assert "### Fairness slices: m.x" in report
    assert check_files(tmp_path, m) == []
    (tmp_path / "model.txt").write_text("changed")
    assert check_files(tmp_path, m) == ["model.txt"]
    (tmp_path / "model.txt").unlink()
    assert check_files(tmp_path, m) == ["model.txt"]
    assert not (tmp_path / METRICS).with_suffix(".tmp").exists()


def test_read_metrics_without_artifact(tmp_path: Path) -> None:
    assert read_metrics(tmp_path / "absent") is None


def test_default_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("ATRA", str(tmp_path))
    assert default_root() == tmp_path / "out"
    monkeypatch.delenv("ATRA")
    assert default_root().parts[-3:] == ("var", "models", "t1")


def test_person_split_is_stable_and_proportional() -> None:
    keys = [f"hdt-{i}" for i in range(5000)]
    masks = split_masks(keys)
    shares = {k: v.mean() for k, v in masks.items()}
    assert shares["train"] == pytest.approx(0.6, abs=0.03)
    assert shares["cal"] == pytest.approx(0.2, abs=0.03)
    assert sum(v.sum() for v in masks.values()) == len(keys)
    assert [split_of(k) for k in keys[:50]] == [split_of(k) for k in keys[:50]]


def test_operating_point_reaches_sensitivity() -> None:
    rng = np.random.default_rng(0)
    y = rng.random(500) < 0.3
    p = np.clip(y * 0.4 + rng.random(500) * 0.6, 0, 1)
    t = operating_point(y, p, min_sensitivity=0.9)
    sens, spec = sensitivity_specificity(y, p, t)
    assert sens >= 0.9 and 0 <= spec <= 1
    assert operating_point([0, 0], [0.2, 0.3]) == 0.5


def test_person_slices() -> None:
    person = {"hdt_id": "hdt-7", "sex": "female", "age_years": 3.0, "lga": "Ikeja"}
    s = slices.person_slices(person)
    assert set(s) == set(ATTRIBUTES)
    assert s["age_band"] == "0-4" and s["region"] == "north_west"
    assert s["facility_level"] in slices.config()["facility_level"]["shares"]
    assert s["language"] in slices.config()["language"]["shares"]
    assert slices.person_slices(person) == s
    assert slices.region_of("Nowhere") == "other"
    cols = slices.slice_columns([person, {**person, "hdt_id": "hdt-8", "age_years": 70}])
    assert cols["age_band"] == ["0-4", "60+"]


def test_every_lga_has_one_region() -> None:
    groups = slices.config()["region"]["groups"]
    members = [m for g in groups.values() for m in g]
    assert len(members) == len(set(members)) == 20


def test_ece_and_concordance() -> None:
    assert ece([0, 1, 0, 1], [0.0, 1.0, 0.0, 1.0]) == pytest.approx(0.0)
    assert ece([0, 0], [1.0, 1.0]) == pytest.approx(1.0)
    assert concordance([1, 2, 3], [1, 1, 1], [3, 2, 1]) == pytest.approx(1.0)
    assert concordance([1, 2, 3], [1, 1, 1], [1, 2, 3]) == pytest.approx(0.0)


def test_slice_report_flags_and_markdown() -> None:
    rng = np.random.default_rng(1)
    n = 400
    sex = np.where(np.arange(n) % 2 == 0, "female", "male")
    y = rng.random(n) < 0.4
    # Informative scores for one sex, noise for the other: a large AUROC disparity.
    p = np.where(sex == "female", np.clip(y * 0.6 + rng.random(n) * 0.4, 0, 1), rng.random(n))
    covered = rng.random(n) < 0.9
    groups = {"sex": sex.tolist(), "region": ["a"] * (n - 5) + ["b"] * 5}
    r = slice_report("m.x", "binary", y, p, groups, covered=covered)
    assert r.metric == "auroc"
    assert r.unavailable == ["age_band", "facility_level", "language"]
    assert any(f.startswith("sex: auroc disparity") for f in r.flags)
    # Region b has 5 rows, below min_n, so region has no disparity.
    assert r.disparity["region"] == {}
    row = next(x for x in r.rows if x.value == "b")
    assert row.n == 5 and row.coverage is not None
    md = r.markdown()
    assert "fewer than 20 rows" in md and "persons" not in md
    assert "| sex | female |" in md and "Flags: sex: auroc disparity" in md
    back = FairnessReport.from_dict(json.loads(json.dumps(r.to_dict())))
    assert back == r


@pytest.mark.parametrize(("task", "metric"), [("multiclass", "macro_f1"),
                                              ("regression", "mae"), ("survival", "c_index")])
def test_slice_report_tasks(task: str, metric: str) -> None:
    rng = np.random.default_rng(2)
    n = 60
    if task == "multiclass":
        y, s = rng.integers(0, 3, n), rng.dirichlet([1, 1, 1], n)
    elif task == "regression":
        y, s = rng.normal(size=n), rng.normal(size=n)
    else:
        y, s = np.column_stack([rng.exponential(size=n), rng.random(n) < 0.7]), rng.random(n)
    r = slice_report("m.x", task, y, s, {"sex": ["f", "m"] * (n // 2)})  # type: ignore[arg-type]
    assert r.metric == metric
    assert all(row.metric is not None for row in r.rows)
    assert all((row.ece is not None) == (task == "multiclass") for row in r.rows)


def test_single_class_slice_has_no_metric() -> None:
    r = slice_report("m.x", "binary", [1, 1, 0, 0], [0.9, 0.8, 0.1, 0.2],
                     {"sex": ["f", "f", "m", "m"]}, min_n=1)
    assert all(row.metric is None for row in r.rows)
    assert r.disparity["sex"] == {}
