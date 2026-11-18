"""Text metrics of the evaluation report: chrF (sacrebleu) and word error rate."""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence


def chrf(hypotheses: Sequence[str], references: Sequence[str]) -> float:
    """Corpus chrF (character n-gram F-score, beta 2, 0 to 100) with sacrebleu defaults."""
    from sacrebleu.metrics.chrf import CHRF

    return float(CHRF().corpus_score(list(hypotheses), [list(references)]).score)


def normalise(text: str) -> str:
    """Lower case, no punctuation, single spaces; keeps letters with their diacritics."""
    text = unicodedata.normalize("NFC", text).lower()
    text = re.sub(r"[^\w\s\u0300-\u036f]", " ", text)
    return " ".join(text.split())


def edit_distance(a: Sequence[str], b: Sequence[str]) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i]
        for j, y in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y)))
        prev = cur
    return prev[-1]


def wer(hypothesis: str, reference: str) -> float:
    """Word error rate after `normalise`; 1.0 for an empty reference with a non-empty hypothesis."""
    ref, hyp = normalise(reference).split(), normalise(hypothesis).split()
    if not ref:
        return 0.0 if not hyp else 1.0
    return edit_distance(hyp, ref) / len(ref)
