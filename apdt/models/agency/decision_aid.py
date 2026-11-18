"""Shared decision-making: the decision aid (design 05, 5.5.4).

The options grid lists, for each option, its benefits, harms, uncertainty, cost and burden.
Benefits and harms come from the option's kb entry and the safety checks, so every line has a
source. The text is passed to the language and literacy hooks; the grid also carries the
text for audio. The patient's choice and questions are written to the agency record.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from apdt.models.context import kb, param
from apdt.models.treatment.options import Option
from apdt.records.agency import AgencyRecord

type TextAdapter = Callable[[str, str, str], str]
"""(text, language, literacy level) → adapted text; the converser plugs in here."""


def literacy_level(correct_answers: int) -> str:
    """The level for a score on the three-item screening question."""
    for level, (lo, hi) in param("literacy_levels").items():
        if lo <= correct_answers <= hi:
            return str(level)
    raise ValueError(f"score {correct_answers} is outside 0 to 3")


def _names(option: Option) -> str:
    return " + ".join(d.drug for d in option.doses) or option.drug_class or option.option_id


def _burden(option: Option) -> dict[str, Any]:
    burden: dict[str, Any] = {}
    for d in option.doses:
        for key in ("doses_per_day", "route", "duration_days"):
            if key in d.schedule:
                burden.setdefault(key, d.schedule[key])
    return burden


def build(options: Sequence[Option], *, language: str = "en", literacy: str = "medium",
          uncertainty: Mapping[str, str] | None = None, cost_ngn: Mapping[str, float] | None = None,
          adapt: TextAdapter | None = None) -> dict[str, Any]:
    adapt = adapt or (lambda text, _lang, _level: text)
    rows: list[dict[str, Any]] = []
    for o in options:
        content = kb().entry(o.option_id).content()
        benefits: list[dict[str, Any]] = [
            {"text": f"{o.preference.replace('_', ' ')} treatment in the guideline",
             "citation": [c.model_dump() for c in o.citations]}]
        if content.get("note"):
            benefits.append({"text": str(content["note"]), "citation": []})
        harms: list[dict[str, Any]] = [
            {"text": f"{i.summary} {i.management or ''}".strip(), "severity": i.severity,
             "source": i.ix_id} for i in o.issues]
        row: dict[str, Any] = {
            "option_id": o.option_id, "name": _names(o), "benefits": benefits, "harms": harms,
            "uncertainty": (uncertainty or {}).get(o.option_id, "not estimated"),
            "cost_ngn": (cost_ngn or {}).get(o.option_id), "burden": _burden(o)}
        summary = (f"{row['name']}. " + " ".join(b["text"] for b in benefits)
                   + (" Risks: " + " ".join(h["text"] for h in harms) if harms else ""))
        row["text"] = adapt(summary, language, literacy)
        rows.append(row)
    grid = {"language": language, "literacy": literacy, "options": rows,
            "audio": {"language": language, "text": " ".join(r["text"] for r in rows)}}
    return grid


async def record_decision(agency: AgencyRecord, hdt_id: str, option_id: str,
                          questions: Sequence[str] = (), *, channel: str = "ussd",
                          episode_id: str | None = None) -> dict[str, Any]:
    """Store the choice as a QuestionnaireResponse and each question for the care team."""
    response = await agency.answers(hdt_id, "decision-aid", {"chosen_option": option_id})
    for q in questions:
        await agency.ask(hdt_id, q, channel=channel, episode_id=episode_id)
    return response
