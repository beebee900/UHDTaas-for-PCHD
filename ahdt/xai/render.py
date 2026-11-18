"""Audience rendering of a structured explanation (design 04, 4.6.1 and 4.6.3).

`render` writes the English text of an `AHDTExplanation` for an audience. Every number
in the text comes from the explanation. `readability` checks the reading level: Flesch
reading ease for English and a sentence-length cap for the other languages.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from atra import contracts as c

type Audience = str

LANGUAGES: Mapping[str, str] = {"en": "English", "yo": "Yoruba", "ha": "Hausa", "ig": "Igbo",
                                "pcm": "Nigerian Pidgin"}
FLESCH_MIN = 60.0
SENTENCE_WORDS_MAX = 20


@dataclass(frozen=True)
class Profile:
    drivers: int
    plain: bool
    counterfactuals: bool
    saliency: bool = True


# Design 04, 4.6.1: clinician sees the top five drivers and a counterfactual; the patient
# sees two drivers in plain words and what they can change.
PROFILES: Mapping[str, Profile] = {
    "clinician": Profile(5, False, True),
    "patient": Profile(2, True, True, saliency=False),
    "pharmacist": Profile(5, False, True),
    "nurse": Profile(3, True, True),
    "radiologist": Profile(5, False, False),
}

_RISE = {"up": "raises", "down": "lowers"}


def humanise(name: str) -> str:
    text = re.sub(r"[_.]+", " ", name).strip()
    return re.sub(r"\s+", " ", text)


def title_of(model_id: str) -> str:
    return humanise(model_id.rsplit(".", 1)[-1])


def _number(v: Any) -> str:
    if isinstance(v, bool):
        return "yes" if v else "no"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if abs(v) < 1000 else f"{v:.0f}"
    return str(v)


def _drivers(e: c.AHDTExplanation, p: Profile) -> str:
    top = sorted(e.drivers, key=lambda d: -abs(d.contribution))[:p.drivers]
    if not top:
        return ""
    if p.plain:
        parts = [f"{humanise(d.feature)} {_RISE[d.direction]} the result" for d in top]
        return "The main reasons: " + "; ".join(parts) + "."
    parts = [f"{humanise(d.feature)}"
             + (f" ({_number(d.value)})" if d.value is not None else "")
             + f" {_RISE[d.direction]} it by {_number(d.contribution)}" for d in top]
    return "Main drivers: " + "; ".join(parts) + "."


def _uncertainty(e: c.AHDTExplanation) -> str:
    u = e.uncertainty
    if "lower" in u and "upper" in u:
        level = u.get("level")
        pct = f"{round(float(level) * 100)} percent " if level is not None else ""
        return f"The {pct}range is {_number(u['lower'])} to {_number(u['upper'])}."
    if "self_consistency" in u:
        return f"The answers agree to {_number(u['self_consistency'])}."
    return ""


def _counterfactuals(e: c.AHDTExplanation, p: Profile) -> str:
    if not p.counterfactuals or not e.counterfactuals:
        return ""
    cf = e.counterfactuals[0]
    changes = ", ".join(f"{humanise(k)} to {_number(v)}" for k, v in cf.changes.items())
    outcome = cf.outcome
    if isinstance(outcome, Mapping):
        outcome = next((v for k, v in outcome.items() if k != "change"), None)
    tail = f", the result would be {_number(outcome)}" if outcome is not None else ""
    lead = "If you changed" if p.plain else "If"
    return f"{lead} {changes}{tail}."


def render(e: c.AHDTExplanation, audience: str, *, output: float | None = None,
           kind: str = "tabular", title: str | None = None, label: str | None = None) -> str:
    """English text of the explanation for `audience`. `label` names the predicted class of
    a signal or graph model."""
    p = PROFILES[audience]
    name = title or title_of(e.model_id)
    if kind in ("signal", "graph") and not p.saliency:
        head = f"A computer program checked your {name}."
        return head + (f" It found {humanise(label)} most likely." if label else "")
    head = f"The {name} result is {_number(output)}." if output is not None \
        else f"This is the explanation of the {name} result."
    parts = [head, _drivers(e, p), _counterfactuals(e, p), _uncertainty(e)]
    return " ".join(x for x in parts if x)


# ---------------------------------------------------------------------------
# Reading level
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[A-Za-z']+")


def _syllables(word: str) -> int:
    groups = re.findall(r"[aeiouy]+", word.lower())
    n = len(groups)
    if word.lower().endswith("e") and n > 1 and not word.lower().endswith("le"):
        n -= 1
    return max(n, 1)


def _sentence_list(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.!?])\s+", text.strip()) if s]


def flesch_reading_ease(text: str) -> float:
    words = _WORD.findall(text)
    sentences = _sentence_list(text)
    if not words or not sentences:
        return 100.0
    syllables = sum(_syllables(w) for w in words)
    return 206.835 - 1.015 * (len(words) / len(sentences)) - 84.6 * (syllables / len(words))


def longest_sentence(text: str) -> int:
    return max((len(s.split()) for s in _sentence_list(text)), default=0)


def readability(text: str, language: str = "en") -> dict[str, Any]:
    """English: Flesch reading ease of at least 60. Other languages: no sentence over
    20 words. `ok` is the verdict."""
    if language == "en":
        score = flesch_reading_ease(text)
        return {"language": language, "metric": "flesch_reading_ease", "value": score,
                "ok": score >= FLESCH_MIN}
    longest = longest_sentence(text)
    return {"language": language, "metric": "longest_sentence_words", "value": longest,
            "ok": longest <= SENTENCE_WORDS_MAX}
