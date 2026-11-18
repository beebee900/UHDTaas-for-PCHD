"""The data rules of the VM jobs, on small local fixtures (the datasets stay on the VM)."""

import json
from collections.abc import Sequence
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from numpy.typing import NDArray

from ahdt.models.ml import ecg, stress


def test_aami_beat_map() -> None:
    expected = {"N": "NLRej", "S": "AaJS", "V": "VE", "F": "F", "Q": "/fQ"}
    for k, (cls, symbols) in enumerate(expected.items()):
        assert ecg.BEAT_CLASSES[k] == cls
        assert all(ecg.SYMBOL_CLASS[s] == k for s in symbols)
    # Rhythm and noise annotations are not beats.
    assert not {"+", "~", "|", "x", "!"} & set(ecg.SYMBOL_CLASS)


@pytest.mark.parametrize(("comment", "sex", "band"), [
    ("69 M 1085 1629 x1", "male", "60+"), ("32 F 1567 1704 x1", "female", "18-39"),
    ("-1 M", "male", "unknown"), ("? ?", "unknown", "unknown"), ("", "unknown", "unknown")])
def test_mitdb_demographics(comment: str, sex: str, band: str) -> None:
    assert ecg.demographics(comment) == {"sex": sex, "age_band": band}


def _ptbxl(root: Path, rhythm: Sequence[str], records: dict[int, str]) -> None:
    codes = [*rhythm, "NORM", "MI"]
    pd.DataFrame({"rhythm": [1.0] * len(rhythm) + [np.nan, np.nan]},
                 index=pd.Index(codes, name="")).to_csv(root / "scp_statements.csv")
    pd.DataFrame({"ecg_id": list(records), "scp_codes": list(records.values())}
                 ).to_csv(root / "ptbxl_database.csv", index=False)


def test_ptbxl_rhythm_labels(tmp_path: Path) -> None:
    _ptbxl(tmp_path, ["SR", "STACH", "SARRH", "SBRAD", "AFIB", "PACE"], {
        1: "{'NORM': 100.0, 'SR': 0.0}", 2: "{'AFIB': 100.0, 'SR': 0.0}",
        3: "{'MI': 50.0, 'PACE': 0.0}", 4: "{'NORM': 100.0}", 5: "{'SBRAD': 0.0}"})
    db = ecg.rhythm_labels(tmp_path)
    assert db["label"].to_dict() == {1: 0, 2: 1, 3: 2, 5: 0}
    assert [ecg.RHYTHM_CLASSES[i] for i in db["label"]] == ["sinus", "af", "other", "sinus"]


def test_ptbxl_rejects_unknown_rhythm_codes(tmp_path: Path) -> None:
    _ptbxl(tmp_path, ["SR", "AFIB"], {1: "{'SR': 0.0}"})
    with pytest.raises(ValueError, match="STACH"):
        ecg.rhythm_labels(tmp_path)


def test_stress_runs() -> None:
    label = np.asarray([1, 1, 2, 2, 2, 1, 1])
    index = np.asarray([0, 1, 2, 3, 9, 10, 11])
    assert stress._runs(label, index) == [(0, 2), (2, 4), (4, 5), (5, 7)]
    assert stress._runs(np.asarray([3, 3]), np.asarray([5, 6])) == [(0, 2)]


def test_stress_readme(tmp_path: Path) -> None:
    path = tmp_path / "S2_readme.txt"
    path.write_text("### Personal information ###\nAge: 27\nHeight (cm): 175\n"
                    "Weight (kg): 80\nGender: male\nDominant hand: right\n")
    assert stress.readme(path) == {"sex": "male", "age_band": "18-39"}
    path.write_text("nothing here\n")
    assert stress.readme(path) == {"sex": "unknown", "age_band": "unknown"}


class FakeEmbedder:
    dim = 8

    def __init__(self) -> None:
        self.calls = 0

    def passages(self, texts: Sequence[str], *, batch_size: int = 32) -> NDArray[np.float32]:
        self.calls += 1
        v = np.asarray([[len(t) % 7 + k for k in range(self.dim)] for t in texts],
                       dtype=np.float32)
        out: NDArray[np.float32] = v / np.linalg.norm(v, axis=1, keepdims=True)
        return out


def test_dense_index_build_resumes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apdt.knowledge import dense_index, retrieval
    from apdt.knowledge.sections import TREES, load_tree

    trees = sorted(TREES.glob("*.json"), key=lambda p: p.stat().st_size)
    if not trees:
        pytest.skip("no section trees in var/kb_sections")
    monkeypatch.setattr(retrieval, "INDEX_DIR", tmp_path / "index")
    monkeypatch.setattr(dense_index, "INDEX_DIR", tmp_path / "index")
    emb = FakeEmbedder()
    index = retrieval.GuidelineIndex([load_tree(trees[0].stem)], embedder=emb)  # type: ignore[arg-type]
    n = len(index.passages)
    assert n >= 2
    shard = max(1, n // 2)
    work = tmp_path / "work"
    assert dense_index.build(index, shard=shard, max_shards=1, work_root=work) is None
    assert emb.calls == 1
    npy = dense_index.build(index, shard=shard, work_root=work)
    assert npy is not None and npy.parent == tmp_path / "index"
    assert emb.calls == len(range(0, n, shard))
    arr = np.load(npy)
    assert arr.shape == (n, FakeEmbedder.dim) and arr.dtype == np.float32
    ids = json.loads(npy.with_name(npy.stem + ".ids.json").read_text())
    assert ids == [u.uid for u in index.passages]
    calls = emb.calls
    np.testing.assert_array_equal(index.embeddings(), arr)
    assert dense_index.build(index, shard=shard, work_root=work) == npy
    assert emb.calls == calls


def test_dense_index_needs_embedder() -> None:
    from apdt.knowledge import dense_index

    class NoEmbedder:
        embedder = None

    with pytest.raises(RuntimeError):
        dense_index.build(NoEmbedder())  # type: ignore[arg-type]
