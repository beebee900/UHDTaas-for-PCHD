"""Prompts shared by training, evaluation and the live service.

`SYSTEM` is the system prompt the LoRA adapters are trained with; the service must send the
same sentence for the adapters to behave as evaluated. `HOSTED_RULES` is added for the hosted
model only.
"""

from __future__ import annotations

from collections.abc import Sequence

SYSTEM = ("You are a health assistant for patients in Nigeria. Reply in {lang} in one or two "
          "short sentences.")
TRANSLATE = "Translate to {lang}: {text}"
HOSTED_RULES = ("Do not diagnose and do not change medicine doses. For anything urgent or "
                "unclear, tell the patient to contact their care team or the nearest clinic.")
FACTS_HEADING = "Facts you may use:"


def system_prompt(lang_name: str, facts: Sequence[str] = (), *, hosted: bool = False) -> str:
    parts = [SYSTEM.format(lang=lang_name)]
    if hosted:
        parts.append(HOSTED_RULES)
    if facts:
        parts.append(FACTS_HEADING + "\n" + "\n".join(f"- {f}" for f in facts))
    return "\n".join(parts)
