"""Output rail for explanation text (design 04, 4.6.3).

A rendered or localised explanation may state only what the structured explanation
holds. `Facts` collects the numbers of the structure. `check` rejects a text with a number
the structure does not support, or with a dosing statement the structure does not make.

`NemoOutputRail` runs the same check as a NeMo Guardrails output rail, so the rail
sits in the same place as the other guardrails of the platform (design 01, Layer 7).
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any

from atra import contracts as c

NUMBER = re.compile(r"(?<![\w.])-?\d+(?:[.,]\d+)?(?=%|\b)")
DOSING = re.compile(r"\b(?:mg|mcg|ug|g|ml|mL|iu|IU|units?|tablets?|capsules?|doses?)\b")
WITHHELD = "The explanation was withheld because it states something the result does not support."


def _flatten(value: Any) -> Iterable[float]:
    if isinstance(value, bool):
        return
    if isinstance(value, int | float):
        yield float(value)
    elif isinstance(value, Mapping):
        for v in value.values():
            yield from _flatten(v)
    elif isinstance(value, list | tuple):
        for v in value:
            yield from _flatten(v)


@dataclass(frozen=True)
class Facts:
    """The numbers and quantities the structure supports."""

    numbers: frozenset[float] = frozenset()
    dosing: bool = False
    items: int = 0
    extra_words: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def of(cls, e: c.AHDTExplanation, *, output: float | None = None,
           extra: Iterable[float] = ()) -> Facts:
        found: list[float] = []
        for d in e.drivers:
            found += [d.contribution, *list(_flatten(d.value))]
        found += list(_flatten(e.uncertainty))
        for cf in e.counterfactuals or []:
            found += [*_flatten(cf.changes), *_flatten(cf.outcome)]
        if e.quality is not None:
            found += list(_flatten(e.quality.model_dump()))
        if output is not None:
            found.append(output)
        found += list(extra)
        items = max(len(e.drivers), len(e.counterfactuals or []), 3)
        return cls(frozenset(found), dosing=False, items=items)


@dataclass(frozen=True)
class Verdict:
    ok: bool
    unsupported: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def _supported(token: str, percent: bool, facts: Facts) -> bool:
    value = float(token.replace(",", "."))
    digits = _decimals(token.replace(",", "."))
    tol = 0.5 * 10 ** -digits + 1e-9
    for a in facts.numbers:
        candidates = (a * 100.0, a) if percent else (a, a * 100.0)
        if any(abs(round(x, digits) - value) <= tol or abs(x - value) <= tol
               for x in candidates):
            return True
    return float(value).is_integer() and 0 <= value <= facts.items


def check(text: str, facts: Facts) -> Verdict:
    """Reject text with a number or a dosing quantity that `facts` does not support."""
    unsupported = []
    for m in NUMBER.finditer(text):
        token = m.group(0)
        percent = text[m.end():m.end() + 1] == "%"
        if not _supported(token, percent, facts):
            unsupported.append(token)
    reasons = []
    if unsupported:
        reasons.append("number not in the explanation: " + ", ".join(unsupported))
    if not facts.dosing and DOSING.search(text):
        reasons.append("dosing statement not in the explanation")
    return Verdict(not reasons, tuple(unsupported), tuple(reasons))


CONFIG_YAML = """
models: []
rails:
  output:
    flows:
      - check explanation facts
"""

COLANG = f"""
define bot refuse explanation
  "{WITHHELD}"

define flow check explanation facts
  $supported = execute check_explanation_facts(text=$bot_message)
  if not $supported
    bot refuse explanation
    stop
"""


class NemoOutputRail:
    """The facts check as a NeMo Guardrails output rail.

    The candidate text is the bot message the rail inspects; the rail either returns it
    or replaces it with the withheld notice.
    """

    def __init__(self) -> None:
        from nemoguardrails import RailsConfig

        self.config = RailsConfig.from_content(colang_content=COLANG, yaml_content=CONFIG_YAML)
        self._facts: Facts | None = None

    async def _generate(self, text: str, facts: Facts) -> str:
        from langchain_core.language_models.llms import LLM
        from nemoguardrails import LLMRails
        from nemoguardrails.integrations.langchain.llm_adapter import LangChainLLMAdapter

        class Candidate(LLM):
            reply: str = ""

            @property
            def _llm_type(self) -> str:
                return "candidate"

            def _call(self, prompt: str, stop: list[str] | None = None, run_manager: Any = None,
                      **kwargs: Any) -> str:
                return self.reply

        rails = LLMRails(self.config, llm=LangChainLLMAdapter(Candidate(reply=text)))

        def check_explanation_facts(text: str = "") -> bool:
            return check(text, facts).ok

        rails.register_action(check_explanation_facts, name="check_explanation_facts")
        out = await rails.generate_async(messages=[{"role": "user", "content": "explain"}])
        return str(out["content"] if isinstance(out, dict) else out)

    def apply(self, text: str, facts: Facts) -> tuple[str, Verdict]:
        verdict = check(text, facts)
        shown = asyncio.run(self._generate(text, facts))
        return shown, verdict


def guard(text: str, facts: Facts, *, nemo: NemoOutputRail | None = None) -> tuple[str, Verdict]:
    """`text` when it passes, otherwise the withheld notice."""
    if nemo is not None:
        return nemo.apply(text, facts)
    verdict = check(text, facts)
    return (text if verdict.ok else WITHHELD), verdict

