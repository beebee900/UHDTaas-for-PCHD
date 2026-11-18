"""Embedding and re-ranker hosts; installing and registering language artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from ahdt.models.language import embed
from ahdt.models.language.embed import EmbeddingHost, RerankerHost
from ahdt.models.language.register import VOICE_ID, install, model_id, register
from atra.backends import Backends
from atra.config import Settings


class FakeEncoder:
    def get_sentence_embedding_dimension(self) -> int:
        return 3

    def encode(self, texts: list[str], batch_size: int, normalize_embeddings: bool) -> Any:
        assert normalize_embeddings
        return np.array([[1.0, 0.0, 0.0] if "fever" in t else [0.0, 1.0, 0.0] for t in texts])


class FakeCross:
    def predict(self, pairs: list[tuple[str, str]]) -> Any:
        return np.array([float(len(set(q.split()) & set(p.split()))) for q, p in pairs])


def test_embedding_host_returns_unit_rows() -> None:
    host = EmbeddingHost("unused")
    host._model = FakeEncoder()
    vecs = host.encode(["fever and chills", "cough"])
    assert vecs.shape == (2, 3) and vecs.dtype == np.float32 and host.dim == 3


def test_reranker_orders_passages_best_first() -> None:
    host = RerankerHost("unused")
    host._model = FakeCross()
    ranked = host.rank("malaria fever symptoms", ["bp is high", "fever symptoms of malaria"])
    assert [i for i, _ in ranked] == [1, 0]
    assert host.rank("fever", ["a", "fever"], top_k=1) == [(1, 1.0)]


def test_default_model_ids() -> None:
    assert embed.BGE_SMALL == "BAAI/bge-small-en-v1.5" and embed.RERANKER.endswith("-base")


def make_artifacts(src: Path, *, corrupt: bool = False) -> None:
    for code in ("yo", "ha"):
        d = src / f"lora-{code}"
        (d / "adapter").mkdir(parents=True)
        (d / "adapter" / "adapter_config.json").write_text("{}")
        weights = d / "adapter" / "adapter_model.safetensors"
        weights.write_bytes(b"weights-" + code.encode())
        from ahdt.models.language.register import sha256

        digest = "0" * 64 if corrupt and code == "ha" else sha256(weights)
        (d / "metrics.json").write_text(json.dumps({
            "steps": 5, "base_model": "Qwen/Qwen2.5-0.5B-Instruct",
            "files": {"adapter/adapter_model.safetensors": digest}}))
        (src / "eval").mkdir(exist_ok=True)
        (src / "eval" / f"{code}.json").write_text(json.dumps({"translation": {
            "n": 40, "chrf_adapter": 12.5, "reference_source": "MAFAND-MT test"}}))


def test_install_copies_checks_and_writes_cards(tmp_path: Path) -> None:
    src, dest, cards = tmp_path / "src", tmp_path / "dest", tmp_path / "cards"
    make_artifacts(src)
    statuses, entries = install(src, dest, cards)
    states = {s.model_id: s.state for s in statuses}
    assert states[model_id("yo")] == "registered" and states[model_id("ig")] == "not trained"
    assert states[VOICE_ID] == "not trained"
    assert (dest / "lora-yo" / "adapter" / "adapter_config.json").is_file()
    card = (cards / f"{model_id('ha')}.md").read_text()
    assert "chrf = 12.5" in card and "CC BY-NC 4.0" in card and "not verified" in card
    assert {e.model_id for e, _ in entries} == {model_id("yo"), model_id("ha")}


def test_install_rejects_a_changed_file(tmp_path: Path) -> None:
    src = tmp_path / "src"
    make_artifacts(src, corrupt=True)
    statuses, entries = install(src, tmp_path / "dest", None)
    bad = next(s for s in statuses if s.model_id == model_id("ha"))
    assert bad.state == "artifact mismatch" and len(entries) == 1


async def test_register_writes_entries_to_the_registry(tmp_path: Path) -> None:
    src = tmp_path / "src"
    make_artifacts(src)
    backends = Backends(Settings(var_dir=tmp_path), "ahdt", ephemeral=True)
    try:
        await register(backends.models, src=src, dest=tmp_path / "dest", cards_dir=None)
        entry = await backends.models.get(model_id("yo"))
        assert entry.family.value == "slm" and entry.validation is not None
        assert entry.validation.metric == "chrf" and entry.validation.value == 12.5
    finally:
        await backends.close()
