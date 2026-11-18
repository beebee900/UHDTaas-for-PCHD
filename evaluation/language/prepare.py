"""Build the LoRA training and evaluation sets of each language (design 06, 6.6).

    python -m evaluation.language.prepare

Inputs: the English dialogues, `translations.json` (Yoruba, Hausa, Igbo by NLLB), the Pidgin
template text, MENYO-20k (Yoruba) and MAFAND-MT (all four languages). Outputs in
`$DATA/sft/`: `sft_<lang>.jsonl` (chat examples) and `eval_<lang>.json`.

Held-out data follows the template slot, not the dialogue: every sixth symptom, condition,
vaccine or action is removed from training and used only for evaluation, because the
dialogue sentences repeat across dialogues.
Training mixes dialogue examples with a few translation-instruction examples from the human
parallel corpora, which carry the fluency; the dialogue examples carry the style.
"""

from __future__ import annotations

import json
import random
import unicodedata
import zipfile
from typing import Any

from ahdt.models.language.prompts import SYSTEM, TRANSLATE
from evaluation.language import common

MT_TRAIN = {"en2l": 200, "l2en": 100}
MT_TEST = 60
MAX_WORDS = 30
MAFAND_CODE = {"yo": "yor", "ha": "hau", "ig": "ibo", "pcm": "pcm"}


def clean(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).replace("﻿", "").split())


def usable(en: str, other: str) -> bool:
    n = len(en.split())
    return 3 <= n <= MAX_WORDS and 3 <= len(other.split()) <= 2 * MAX_WORDS


def mafand(lang: str, split: str) -> list[tuple[str, str]]:
    code = MAFAND_CODE[lang]
    path = common.DATA / "mafand" / f"en-{code}" / f"{split}.json"
    pairs = []
    for row in common.read_jsonl(path):
        t = row["translation"]
        en, other = clean(t["en"]), clean(t[code])
        if usable(en, other):
            pairs.append((en, other))
    return pairs


def menyo(split: str) -> list[tuple[str, str]]:
    pairs = []
    with zipfile.ZipFile(common.DATA / "menyo-20k.zip") as z:
        name = next(n for n in z.namelist() if n.endswith(f"/data/{split}.tsv"))
        for line in z.read(name).decode("utf-8").splitlines()[1:]:
            parts = line.split("\t")
            if len(parts) == 2:
                en, yo = clean(parts[0]), clean(parts[1])
                if usable(en, yo):
                    pairs.append((en, yo))
    return pairs


def human_pairs(lang: str, split: str) -> list[tuple[str, str]]:
    pairs = mafand(lang, split)
    return pairs + menyo(split) if lang == "yo" else pairs


def held_out_slots(dialogues: list[dict[str, Any]]) -> set[str]:
    out: set[str] = set()
    for kind in sorted({d["kind"] for d in dialogues}):
        slots = sorted({d["slot"] for d in dialogues if d["kind"] == kind})
        if len(slots) >= 6:
            out.update(slots[5::6])
    return out


def localise(dialogue: dict[str, Any], lang: str, tr: dict[str, dict[str, str]]
             ) -> list[dict[str, str]]:
    msgs = []
    for t in dialogue["turns"]:
        text = t["pcm"] if lang == "pcm" else tr[lang][t["en"]]
        msgs.append({"role": t["role"], "content": text, "en": t["en"]})
    return msgs


def build(lang: str, dialogues: list[dict[str, Any]], tr: dict[str, dict[str, str]],
          seed: int = 0) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rng = random.Random(f"{seed}-{lang}")
    name = common.NAMES[lang]
    hold = held_out_slots(dialogues)
    system = {"role": "system", "content": SYSTEM.format(lang=name)}
    train: list[dict[str, Any]] = []
    eval_dialogues: list[dict[str, Any]] = []
    for d in dialogues:
        msgs = localise(d, lang, tr)
        if d["slot"] in hold:
            for i, m in enumerate(msgs):
                if m["role"] == "assistant" and i > 0:
                    eval_dialogues.append({
                        "id": f"{d['id']}-{i}", "kind": d["kind"],
                        "context": [system, *({"role": x["role"], "content": x["content"]}
                                              for x in msgs[:i])],
                        "reference": m["content"], "english": m["en"]})
        else:
            train.append({"kind": "dialogue", "messages": [
                system, *({"role": m["role"], "content": m["content"]} for m in msgs)]})
    pairs = human_pairs(lang, "train")
    rng.shuffle(pairs)
    n1, n2 = MT_TRAIN["en2l"], MT_TRAIN["l2en"]
    for en, other in pairs[:n1]:
        train.append({"kind": "mt", "messages": [
            {"role": "system", "content": system["content"]},
            {"role": "user", "content": TRANSLATE.format(lang=name, text=en)},
            {"role": "assistant", "content": other}]})
    for en, other in pairs[n1:n1 + n2]:
        train.append({"kind": "mt", "messages": [
            {"role": "system", "content": system["content"]},
            {"role": "user", "content": TRANSLATE.format(lang="English", text=other)},
            {"role": "assistant", "content": en}]})
    rng.shuffle(train)
    test = human_pairs(lang, "test")
    rng.shuffle(test)
    rng.shuffle(eval_dialogues)
    held = {"mt": [{"english": en, "reference": other} for en, other in test[:MT_TEST]],
            "dialogue": eval_dialogues}
    return train, held


def main() -> int:
    dialogues = common.read_jsonl(common.HERE / "data" / "dialogues_en.jsonl")
    tr_path = common.DATA / "translations.json"
    tr = json.loads(tr_path.read_text(encoding="utf-8")) if tr_path.exists() else {}
    out = common.DATA / "sft"
    for lang in common.LANGS:
        if lang != "pcm" and lang not in tr:
            common.log(f"{lang}: no translations yet, skipped")
            continue
        train, held = build(lang, dialogues, tr)
        common.write_jsonl(out / f"sft_{lang}.jsonl", train)
        common.write_json(out / f"eval_{lang}.json", held)
        kinds = {k: sum(1 for r in train if r["kind"] == k) for k in ("dialogue", "mt")}
        common.log(f"{lang}: train {kinds}, eval mt {len(held['mt'])}, "
                   f"eval dialogue {len(held['dialogue'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
