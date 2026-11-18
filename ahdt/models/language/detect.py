"""Language detection for en, yo, ha, ig and pcm.

No off-the-shelf detector covers Hausa, Igbo and Pidgin together, so this is a small scored
lexicon: each locale has marker characters (diacritics and letters that its orthography uses
and the others do not) and function words. Every token adds the weight of the locales it
belongs to; the highest total wins. Pidgin is English-lexified, so English words give Pidgin a
small share and its own markers a large one. The result carries a confidence, the share of the
winner in the total score. A caller that knows the user's language passes it explicitly and
skips detection. Accuracy on held-out sentences is reported in `evaluation/language/`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ahdt.models.language.locales import DEFAULT_LOCALE


def _words(text: str) -> frozenset[str]:
    return frozenset(unicodedata.normalize("NFC", text).split())


WORDS: dict[str, frozenset[str]] = {
    "en": _words("""
        the and is are was were you your have has had not do does did what how my this that
        can will would please thank thanks it in on at be to of for with from i am we they he
        she there when where which who been if or but about after before take feel pain"""),
    "pcm": _words("""
        wetin dey abeg wahala wey una pikin sabi dem oga wan don sef dis dat bodi na pesin
        oya sha wia wen"""),
    "yo": _words("""
        ni ti kí ní ń jẹ́ rẹ mi wọn wọ́n ṣe bí kò ó mo ẹ láti fún pẹ̀lú àti sí nínú lọ wá lè
        náà yìí tí ṣùgbọ́n ọ̀ ẹ̀ ṣé jẹ àwọn ìwọ èmi o"""),
    "ha": _words("""
        da na ta ya ne ce ba shi ita kuma ko cikin ga wannan wancan don domin yana tana suna
        ina kana kina ciwon lafiya ka ku mu su ni kai ke ki ban bai zai za sai amma kamar
        daga zuwa tare har yau yaushe me wane wace"""),
    "ig": _words("""
        na bụ ka nke ọ m gị ndị maka ahụ anyị unu ha ya ị n'ime nwere dị gwa ma mana ihe
        ụbọchị dọkịta biko daalụ kedu ọ̀ bụla ọbụla a"""),
}
# Weight of a word that belongs to the locale's list. Pidgin markers outweigh the English
# words that Pidgin shares with English.
WORD_WEIGHT = {"en": 1.0, "pcm": 3.0, "yo": 1.2, "ha": 1.2, "ig": 1.2}
ENGLISH_IN_PCM = 0.6
CHARS: dict[str, str] = {
    "yo": "ẹṣ",
    "ig": "ịụṅ",
    "ha": "ɓɗƙƴ",
}
CHAR_WEIGHT = {"yo": 2.5, "ig": 2.5, "ha": 3.0}
SHARED_CHARS = {"ọ": ("yo", "ig")}
TONE_MARKS = frozenset("àáèéìíòóùúńǹ̀́")
TONE_WEIGHT = 0.4
TOKEN = re.compile(r"[\w'’̀-ͯ]+", re.UNICODE)


@dataclass(frozen=True)
class Detection:
    locale: str
    confidence: float
    scores: dict[str, float]


def _norm(text: str) -> str:
    return unicodedata.normalize("NFC", text.lower())


def detect_language(text: str, *, default: str = DEFAULT_LOCALE) -> Detection:
    """The most likely locale of `text`; `default` with confidence 0 when no signal is found."""
    text = _norm(text)
    scores = dict.fromkeys(WORDS, 0.0)
    for token in TOKEN.findall(text):
        for locale, words in WORDS.items():
            if token in words:
                scores[locale] += WORD_WEIGHT[locale]
        if token in WORDS["en"]:
            scores["pcm"] += ENGLISH_IN_PCM
    for ch in text:
        for locale, chars in CHARS.items():
            if ch in chars:
                scores[locale] += CHAR_WEIGHT[locale]
        for locale in SHARED_CHARS.get(ch, ()):
            scores[locale] += CHAR_WEIGHT[locale] / 2
        if ch in TONE_MARKS:
            scores["yo"] += TONE_WEIGHT
    total = sum(scores.values())
    if total <= 0:
        return Detection(default, 0.0, scores)
    best = max(scores, key=lambda k: scores[k])
    return Detection(best, scores[best] / total, scores)
