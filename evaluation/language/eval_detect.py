"""Accuracy of `detect_language` on human-written news sentences.

    python -m evaluation.language.eval_detect

Test sentences: the MAFAND-MT test files (English side, and the Hausa, Igbo, Pidgin and Yoruba
sides), up to 300 per language. Output: `$ATRA/out/wp14d/eval/detection.json` with accuracy per
language and the most frequent confusions.
"""

from __future__ import annotations

from collections import Counter

from ahdt.models.language.detect import detect_language
from evaluation.language import common
from evaluation.language.prepare import MAFAND_CODE, clean

LIMIT = 300


def main() -> int:
    sets: dict[str, list[str]] = {"en": []}
    for lang, code in MAFAND_CODE.items():
        rows = common.read_jsonl(common.DATA / "mafand" / f"en-{code}" / "test.json")
        sets[lang] = [clean(r["translation"][code]) for r in rows][:LIMIT]
        if len(sets["en"]) < LIMIT:
            sets["en"] += [clean(r["translation"]["en"]) for r in rows][:LIMIT // 4]
    result = {}
    for lang, texts in sets.items():
        got = Counter(detect_language(t).locale for t in texts)
        result[lang] = {"n": len(texts), "accuracy": got[lang] / len(texts),
                        "predicted": dict(got.most_common())}
        common.log(f"{lang}: {result[lang]['accuracy']:.2f} {dict(got.most_common())}")
    common.write_json(common.OUT / "eval" / "detection.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
