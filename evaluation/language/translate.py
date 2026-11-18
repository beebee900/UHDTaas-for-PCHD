"""Translate the English dialogue sentences into Yoruba, Hausa and Igbo with NLLB-200.

    python -m evaluation.language.translate [--langs yo ha ig]

Design 06, 6.6 names the hosted LLM as the translator; with no hosted-model key available the
distilled 600M NLLB-200 model (CC BY-NC 4.0) does it on the VM. Pidgin has no NLLB code; its
sentences come from the templates of `dialogues.py`. Output: `$ATRA/wp14d/data/translations.json`
mapping language -> {English sentence -> translation}.
"""

from __future__ import annotations

import argparse
import time
from collections.abc import Sequence

from evaluation.language import common
from evaluation.language.dialogues import unique_sentences


class Translator:
    def __init__(self, path: str | None = None, *, batch: int = 8, beams: int = 2) -> None:
        import torch
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        torch.set_num_threads(1)
        path = path or str(common.MODELS / "nllb")
        self.torch = torch
        self.tok = AutoTokenizer.from_pretrained(path)
        self.model = AutoModelForSeq2SeqLM.from_pretrained(path, dtype=torch.float32).eval()
        self.batch, self.beams = batch, beams

    def __call__(self, texts: Sequence[str], src: str, tgt: str) -> list[str]:
        self.tok.src_lang = common.NLLB[src]
        out: list[str] = []
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
        done: dict[int, str] = {}
        for start in range(0, len(order), self.batch):
            idx = order[start:start + self.batch]
            enc = self.tok([texts[i] for i in idx], return_tensors="pt", padding=True,
                           truncation=True, max_length=200)
            with self.torch.no_grad():
                gen = self.model.generate(
                    **enc, forced_bos_token_id=self.tok.convert_tokens_to_ids(common.NLLB[tgt]),
                    num_beams=self.beams, max_new_tokens=200)
            for i, text in zip(idx, self.tok.batch_decode(gen, skip_special_tokens=True),
                               strict=True):
                done[i] = text
        out = [done[i] for i in range(len(texts))]
        return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--langs", nargs="+", default=["yo", "ha", "ig"])
    args = parser.parse_args(argv)
    sentences = unique_sentences(common.read_jsonl(common.HERE / "data" / "dialogues_en.jsonl"))
    if common.smoke():
        sentences = sentences[:6]
    translator = Translator()
    result: dict[str, dict[str, str]] = {}
    for lang in args.langs:
        start = time.time()
        result[lang] = dict(zip(sentences, translator(sentences, "en", lang), strict=True))
        common.log(f"{lang}: {len(sentences)} sentences in {time.time() - start:.0f} s")
        common.write_json(common.DATA / "translations.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
