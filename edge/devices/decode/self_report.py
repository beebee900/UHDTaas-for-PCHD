"""Self-report instruments: FHIR QuestionnaireResponse from the app and ODK submissions.

Both are scored against the kb Questionnaire (`kb/questionnaires/*.json`): each answer's
`ordinalValue` is summed, and the result carries the code of the read-only `total` item
(PHQ-9 44261-6, GAD-7 70274-6). An ODK submission is the XForm instance XML whose root
element's `id` attribute names the Questionnaire; each item is a leaf element `item_{linkId}`
(XML names cannot start with a digit) holding the chosen answer code.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from datetime import datetime
from functools import lru_cache
from typing import Any
from xml.etree import ElementTree

from atra.config import ROOT
from atra.contracts import Code
from edge.devices.decode.observations import CodedReading

ORDINAL = "http://hl7.org/fhir/StructureDefinition/ordinalValue"
QUESTIONNAIRES = ROOT / "kb" / "questionnaires"
ODK_PREFIX = "item_"


class SelfReportError(ValueError):
    pass


def _walk(items: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for item in items:
        yield item
        yield from _walk(item.get("item", []))


@lru_cache(maxsize=32)
def _questionnaire(name: str) -> dict[str, Any]:
    path = QUESTIONNAIRES / f"{name}.json"
    if not path.exists():
        raise SelfReportError(f"no questionnaire {name}")
    q: dict[str, Any] = json.loads(path.read_text())
    return q


def _key(canonical: str) -> str:
    return canonical.split("|")[0].rstrip("/").rsplit("/", 1)[-1]


def score(name: str, answers: Mapping[str, str], time: datetime) -> CodedReading:
    """The total of answer codes by linkId."""
    q = _questionnaire(name)
    items = {i["linkId"]: i for i in _walk(q["item"])}
    total_item = items.get("total")
    if total_item is None or not total_item.get("code"):
        raise SelfReportError(f"questionnaire {name} has no coded total")
    total = 0.0
    for item in items.values():
        if item.get("type") != "choice":
            continue
        code = answers.get(item["linkId"])
        if code is None:
            raise SelfReportError(f"item {item['linkId']} is unanswered")
        option = next((o for o in item["answerOption"] if o["valueCoding"]["code"] == code),
                      None)
        if option is None:
            raise SelfReportError(f"{code!r} is not an option of item {item['linkId']}")
        total += next(e["valueDecimal"] for e in option["extension"] if e["url"] == ORDINAL)
    c = total_item["code"][0]
    return CodedReading(Code(system=c["system"], code=c["code"]), total, "{score}", time)


def from_questionnaire_response(qr: Mapping[str, Any]) -> CodedReading:
    if qr.get("resourceType") != "QuestionnaireResponse" or qr.get("status") != "completed":
        raise SelfReportError("only completed QuestionnaireResponses are scored")
    answers = {i["linkId"]: i["answer"][0]["valueCoding"]["code"]
               for i in _walk(list(qr.get("item", []))) if i.get("answer")}
    return score(_key(str(qr["questionnaire"])), answers,
                 datetime.fromisoformat(str(qr["authored"])))


def from_odk(xml: bytes, time: datetime) -> CodedReading:
    root = ElementTree.fromstring(xml)
    form = root.get("id")
    if not form:
        raise SelfReportError("the submission root has no form id")
    answers = {el.tag.removeprefix(ODK_PREFIX): (el.text or "").strip() for el in root.iter()
               if el.tag.startswith(ODK_PREFIX) and len(el) == 0}
    return score(form, answers, time)
