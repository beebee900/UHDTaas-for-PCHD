"""Metrics, dialogue generation, data preparation and the dataset fetch user agent."""

from __future__ import annotations

import json
import unicodedata
import zipfile
from pathlib import Path

import pytest

from evaluation.datasets import fetch as datasets_fetch
from evaluation.language import common, prepare
from evaluation.language.dialogues import generate, unique_sentences
from evaluation.language.metrics import chrf, normalise, wer
from evaluation.language.train_lora import encode, lr_at, render


def test_chrf_is_100_for_identical_text_and_lower_for_different_text() -> None:
    assert chrf(["Báwo ni ara rẹ"], ["Báwo ni ara rẹ"]) == pytest.approx(100.0)
    assert 0 < chrf(["Báwo ni ara"], ["Báwo ni ara rẹ lónìí"]) < 100
    assert chrf(["xyz"], ["Báwo ni"]) < 5


def test_wer_counts_word_edits_after_normalising() -> None:
    assert wer("Hello, world!", "hello world") == 0.0
    assert wer("hello there world", "hello world") == pytest.approx(0.5)
    assert wer("", "a b c d") == 1.0 and wer("", "") == 0.0
    assert normalise("  Ọ̀dún,  tuntun! ") == unicodedata.normalize("NFC", "ọ̀dún tuntun")


def test_dialogues_are_deterministic_and_cover_all_kinds() -> None:
    a, b = generate(120, seed=3), generate(120, seed=3)
    assert a == b
    assert {d["kind"] for d in a} == {"checkin", "explain", "vaccine", "support", "medicine",
                                      "consent"}
    assert all(t["pcm"] and t["en"] for d in a for t in d["turns"])
    assert 20 < len(unique_sentences(a)) < 400


def write_data(root: Path) -> None:
    for pair, code in (("yor", "yor"), ("hau", "hau"), ("ibo", "ibo"), ("pcm", "pcm")):
        d = root / "mafand" / f"en-{pair}"
        d.mkdir(parents=True)
        for split in ("train", "dev", "test"):
            rows = [{"translation": {"en": f"The health worker visited village number {i} today",
                                     code: f"{code} sentence number {i} for the health visit"}}
                    for i in range(400)]
            (d / f"{split}.json").write_text("\n".join(json.dumps(r) for r in rows))
    tsv = "English\tYoruba\n" + "\n".join(
        f"The nurse gave medicine to patient {i} today\tNọ́ọ̀sì fún aláìsàn {i} ní oògùn lónìí"
        for i in range(60))
    with zipfile.ZipFile(root / "menyo-20k.zip", "w") as z:
        for split in ("train", "dev", "test"):
            z.writestr(f"menyo-20k_MT-master/data/{split}.tsv", tsv)


def test_prepare_holds_out_template_slots_and_mixes_in_translation_pairs(
        tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    write_data(tmp_path)
    monkeypatch.setattr(common, "DATA", tmp_path)
    dialogues = generate(200, seed=0)
    tr = {lang: {s: f"[{lang}] {s}" for s in unique_sentences(dialogues)}
          for lang in ("yo", "ha", "ig")}
    hold = prepare.held_out_slots(dialogues)
    assert hold and all(d["slot"] not in hold or d["kind"] != "medicine" for d in dialogues)
    for lang in common.LANGS:
        train, held = prepare.build(lang, dialogues, tr)
        kinds = [r["kind"] for r in train]
        assert kinds.count("mt") == 300 and kinds.count("dialogue") > 100
        assert len(held["mt"]) == prepare.MT_TEST and held["dialogue"]
        roles = {m["role"] for r in train for m in r["messages"]}
        assert roles == {"system", "user", "assistant"}
        assert all(h["context"][0]["role"] == "system" for h in held["dialogue"])
        first = train[0]["messages"][0]["content"]
        assert common.NAMES[lang] in first


def test_training_examples_mask_everything_but_assistant_turns() -> None:
    class Tok:
        def __call__(self, text: str, add_special_tokens: bool = False) -> dict[str, list[int]]:
            return {"input_ids": [ord(c) for c in text]}

    msgs = [{"role": "system", "content": "S"}, {"role": "user", "content": "Q"},
            {"role": "assistant", "content": "A"}]
    ids, labels = encode(Tok(), msgs, 200)
    trained = "".join(chr(i) for i, y in zip(ids, labels, strict=True) if y != -100)
    assert trained == "A<|im_end|>"
    assert len(ids) == sum(len(t) for t, _ in render(msgs))
    assert len(encode(Tok(), msgs, 10)[0]) == 10


def test_learning_rate_warms_up_then_decays() -> None:
    lrs = [lr_at(s, 100, 2e-4, 5) for s in range(100)]
    assert lrs[0] < lrs[4] == pytest.approx(2e-4) and lrs[-1] < lrs[10]
    assert min(lrs) >= 2e-5 - 1e-12


def test_dataset_fetch_sends_a_descriptive_user_agent(tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    seen: dict[str, str] = {}

    class Response:
        def raise_for_status(self) -> None: ...
        def iter_bytes(self, n: int) -> list[bytes]:
            return [b"data"]
        def __enter__(self) -> Response:
            return self
        def __exit__(self, *a: object) -> None: ...

    def fake_stream(method: str, url: str, **kw: object) -> Response:
        seen.update(kw["headers"])  # type: ignore[arg-type]
        return Response()

    monkeypatch.setattr(datasets_fetch.httpx, "stream", fake_stream)
    monkeypatch.setattr(datasets_fetch, "STORE", tmp_path / "store")
    monkeypatch.setattr(datasets_fetch, "LOCK", tmp_path / "lock.yaml")
    monkeypatch.setattr(datasets_fetch, "load", lambda: [
        {"id": "x", "status": "approved", "url": "https://upload.wikimedia.org/a.svg"}])
    assert datasets_fetch.fetch([]) == {"x": "fetched 4 bytes"}
    assert "atra-health" in seen["User-Agent"] and "https://" in seen["User-Agent"]
