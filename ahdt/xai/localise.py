"""Localisation of explanation text (design 04, 4.6.3).

The structured explanation is rendered in English by `render`. A language model writes it in
yo, ha, ig or pcm. The model's text reaches a person only after the output rail has checked
it against the structure; a text that fails the rail, or a missing model, gives the English
text.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ahdt.xai.rails import Facts, NemoOutputRail, Verdict, guard
from ahdt.xai.render import LANGUAGES, readability
from atra import contracts as c

type Llm = Callable[[str], str]

PROMPT = (
    "Write the explanation below in {language} for a {audience}. Use short sentences and "
    "simple words. Keep every number exactly as written. Add no fact, number or advice "
    "that is not in the text.\n\n{text}")


@dataclass(frozen=True)
class Localised:
    text: str
    language: str
    english: str
    readability: dict[str, object]
    verdict: Verdict
    fell_back: bool
    reason: str | None = None


class Localiser:
    def __init__(self, llm: Llm | None = None, *, nemo: NemoOutputRail | None = None) -> None:
        self.llm = llm
        self.nemo = nemo

    def render(self, e: c.AHDTExplanation, audience: str, language: str, *,
               output: float | None = None) -> Localised:
        if language not in LANGUAGES:
            raise ValueError(f"unsupported language {language}")
        facts = Facts.of(e, output=output)
        english, verdict = guard(e.text, facts, nemo=self.nemo)
        if language == "en":
            return Localised(english, "en", e.text, readability(english, "en"), verdict,
                             False)
        if self.llm is None:
            return Localised(english, "en", e.text, readability(english, "en"), verdict,
                             True, "no language model is available")
        candidate = self.llm(PROMPT.format(language=LANGUAGES[language], audience=audience,
                                           text=e.text))
        shown, verdict = guard(candidate, facts, nemo=self.nemo)
        if not verdict.ok:
            return Localised(english, "en", e.text, readability(english, "en"), verdict,
                             True, "; ".join(verdict.reasons))
        return Localised(shown, language, e.text, readability(shown, language), verdict, False)
