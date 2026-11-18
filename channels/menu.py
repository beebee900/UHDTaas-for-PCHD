"""The menu engine of USSD and the voice IVR, read from `channels/ussd_menu.yaml`.

The engine is a pure function of the inputs of a session. USSD sends all inputs so far
joined by `*` on every request, and the IVR keeps the DTMF digits of the call, so each
request replays the inputs from the main menu. A walk ends in one of:

- a screen to show (`end=False`: wait for the next input)
- a final screen (`end=True`)
- an action for the service to run (`consent`, `check_in`, `ask`, `care_plan`, `reminders`)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from apdt.intake.questionnaires import load as load_questionnaire
from atra.config import ROOT

SPEC = Path(__file__).parent / "ussd_menu.yaml"
CHOICE_TYPES = ("choice", "boolean")


@dataclass
class Step:
    text: str
    end: bool
    language: str
    action: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    node: str = "main"


@dataclass(frozen=True)
class Question:
    link_id: str
    text: str
    type: str
    options: tuple[tuple[str, str], ...]


class Menu:
    def __init__(self, spec: Mapping[str, Any], kb_dir: Path = ROOT / "kb") -> None:
        self.spec = spec
        self.strings: Mapping[str, Mapping[str, str]] = spec["strings"]
        self.menus: Mapping[str, Mapping[str, Any]] = spec["menus"]
        self.consent_items: Sequence[Mapping[str, Any]] = spec["consent_items"]
        self.timeout_s = float(spec["session_timeout_s"])
        self.service_code = str(spec["service_code"])
        self.languages = tuple(spec["languages"])
        self.questions: dict[str, tuple[Question, ...]] = {}
        for name, node in self.menus.items():
            if node.get("kind") == "questionnaire":
                self.questions[name] = _questions(load_questionnaire(node["questionnaire"],
                                                                     kb_dir))

    def t(self, key: str, language: str) -> str:
        entry = self.strings[key]
        return entry.get(language) or entry["en"]

    def _menu_screen(self, name: str, lang: str) -> str:
        node = self.menus[name]
        lines = [self.t(node["text"], lang)]
        lines += [f"{o['key']} {self.t(o['label'], lang)}" for o in node["options"]]
        return "\n".join(lines)

    def _question_screen(self, q: Question, lang: str) -> str:
        options = (q.options if q.type == "choice"
                   else (("yes", self.t("check_in.yes", lang)),
                         ("no", self.t("check_in.no", lang))))
        return "\n".join([q.text, *(f"{i} {label}" for i, (_, label) in
                                    enumerate(options, 1))])

    def _consent_screen(self, index: int, decisions: Mapping[str, bool], lang: str) -> str:
        if index < 0:
            return f"{self.t('consent.intro', lang)}\n1 {self.t('consent.continue', lang)}"
        if index < len(self.consent_items):
            item = self.consent_items[index]
            return (f"{self.t('consent.item.' + item['id'], lang)}\n"
                    f"1 {self.t('consent.allow', lang)}\n2 {self.t('consent.withhold', lang)}")
        withheld = [self.t("consent.item." + i["id"], lang) for i in self.consent_items
                    if not decisions[i["id"]]]
        head = (self.t("consent.summary_none", lang) if not withheld
                else self.t("consent.summary", lang) + " " + ", ".join(withheld))
        return (f"{head}\n1 {self.t('consent.confirm', lang)}\n"
                f"2 {self.t('consent.cancel', lang)}")

    def consent_result(self, decisions: Mapping[str, bool]) -> dict[str, list[str]]:
        purposes: list[str] = []
        withheld: list[str] = []
        for item in self.consent_items:
            allowed = decisions[item["id"]]
            if "purposes" in item and allowed:
                purposes += list(item["purposes"])
            if "category" in item and not allowed:
                withheld.append(str(item["category"]))
        return {"purposes": purposes, "withheld_categories": withheld}

    def walk(self, inputs: Sequence[str], language: str) -> Step:
        lang = language if language in self.languages else "en"
        node = "main"
        index = -1
        answers: dict[str, str] = {}
        decisions: dict[str, bool] = {}

        def final(key: str) -> Step:
            return Step(self.t(key, lang), True, lang, node=node)

        for raw in inputs:
            value = raw.strip()
            spec = self.menus[node]
            kind = spec.get("kind", "menu")
            if kind == "menu":
                option = next((o for o in spec["options"] if o["key"] == value), None)
                if option is None:
                    return final("invalid")
                if "set_language" in option:
                    lang = str(option["set_language"])
                if "end" in option:
                    return final(option["end"])
                if "action" in option:
                    return Step("", True, lang, action=option["action"], node=node)
                node, index = option["next"], -1
                answers, decisions = {}, {}
            elif kind == "questionnaire":
                qs = self.questions[node]
                index = max(index, 0)
                q = qs[index]
                options = q.options if q.type == "choice" else (("yes", ""), ("no", ""))
                if not value.isdigit() or not 1 <= int(value) <= len(options):
                    return final("invalid")
                answers[q.link_id] = options[int(value) - 1][0]
                index += 1
                if index == len(qs):
                    return Step("", True, lang, action=spec["action"],
                                data={"answers": answers}, node=node)
            elif kind == "consent":
                if index < 0:
                    if value != "1":
                        return final("invalid")
                elif index < len(self.consent_items):
                    if value not in ("1", "2"):
                        return final("invalid")
                    decisions[self.consent_items[index]["id"]] = value == "1"
                else:
                    if value == "2":
                        return final("consent.cancelled")
                    if value != "1":
                        return final("invalid")
                    return Step("", True, lang, action=spec["action"],
                                data=self.consent_result(decisions), node=node)
                index += 1
            elif kind == "free_text":
                if not value:
                    return final("invalid")
                return Step("", True, lang, action=spec["action"], data={"text": value},
                            node=node)
        return Step(self._screen(node, index, decisions, lang), False, lang, node=node)

    def _screen(self, node: str, index: int, decisions: Mapping[str, bool], lang: str) -> str:
        spec = self.menus[node]
        kind = spec.get("kind", "menu")
        if kind == "menu":
            return self._menu_screen(node, lang)
        if kind == "questionnaire":
            return self._question_screen(self.questions[node][max(index, 0)], lang)
        if kind == "consent":
            return self._consent_screen(index, decisions, lang)
        return self.t(spec["text"], lang)


def _questions(questionnaire: Mapping[str, Any]) -> tuple[Question, ...]:
    out = []

    def walk(items: Sequence[Mapping[str, Any]]) -> None:
        for item in items:
            if item["type"] in CHOICE_TYPES:
                options = tuple((o["valueCoding"]["code"], o["valueCoding"]["display"])
                                for o in item.get("answerOption", []))
                out.append(Question(item["linkId"], item["text"], item["type"], options))
            walk(item.get("item", []))

    walk(questionnaire.get("item", []))
    return tuple(out)


@lru_cache(maxsize=1)
def default_menu() -> Menu:
    return Menu(yaml.safe_load(SPEC.read_text(encoding="utf-8")))
