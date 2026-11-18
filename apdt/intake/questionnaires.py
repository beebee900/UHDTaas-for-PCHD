"""Questionnaire service (design 05, 5.2.1): SDC `$populate` and `$extract` over the kb
questionnaires, and the item list that the web and Flutter renderers draw.

Both operations are observation-based, as the SDC IG defines them:

- `$populate` fills an item that has `code` and the `sdc-questionnaire-observationLinkPeriod`
  extension from the most recent final, amended or corrected Observation of the subject
  with a matching code inside the period.
- `$extract` makes one Observation per answered item that has `code` and
  `sdc-questionnaire-observationExtract` = true on the item, an ancestor or the root:
  code = all item codes, value = the answer, subject = the response's subject,
  effectiveDateTime = `authored`, derivedFrom = the response.

The kb questionnaires carry item codes only. `served()` adds the two extensions to every
coded item, with a 14-day link period, before a questionnaire is handed out.
"""

from __future__ import annotations

import copy
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from fhir.resources.R4B.observation import Observation
from fhir.resources.R4B.questionnaireresponse import QuestionnaireResponse

from atra.config import ROOT

SDC = "http://hl7.org/fhir/uv/sdc/StructureDefinition/"
EXTRACT = SDC + "sdc-questionnaire-observationExtract"
LINK_PERIOD = SDC + "sdc-questionnaire-observationLinkPeriod"
SURVEY = {"system": "http://terminology.hl7.org/CodeSystem/observation-category",
          "code": "survey"}
DEFAULT_LINK_DAYS = 14
USABLE_STATUS = ("final", "amended", "corrected")
DURATION_UNITS = {"d": timedelta(days=1), "h": timedelta(hours=1), "min": timedelta(minutes=1),
                  "wk": timedelta(weeks=1), "a": timedelta(days=365.25),
                  "mo": timedelta(days=30.4375)}


def load(qid: str, kb_dir: Path = ROOT / "kb") -> dict[str, Any]:
    path = kb_dir / "questionnaires" / f"{qid}.json"
    if not path.exists():
        raise KeyError(qid)
    return dict(json.loads(path.read_text(encoding="utf-8")))


def available(kb_dir: Path = ROOT / "kb") -> list[str]:
    return sorted(p.stem for p in (kb_dir / "questionnaires").glob("*.json"))


def _items(items: Iterable[Mapping[str, Any]],
           extract: bool = False) -> Iterator[tuple[Mapping[str, Any], bool]]:
    for item in items:
        flag = _flag(item, extract)
        yield item, flag
        yield from _items(item.get("item", []), flag)


def _flag(element: Mapping[str, Any], inherited: bool) -> bool:
    for ext in element.get("extension", []):
        if ext.get("url") == EXTRACT:
            return bool(ext.get("valueBoolean"))
    return inherited


def served(questionnaire: Mapping[str, Any], *,
           link_days: int = DEFAULT_LINK_DAYS) -> dict[str, Any]:
    """A copy with the extract and link-period extensions on every coded question."""
    q = copy.deepcopy(dict(questionnaire))

    def mark(items: list[dict[str, Any]]) -> None:
        for item in items:
            if item.get("code") and item.get("type") not in ("group", "display"):
                exts = [e for e in item.get("extension", [])
                        if e.get("url") not in (EXTRACT, LINK_PERIOD)]
                exts += [{"url": EXTRACT, "valueBoolean": True},
                         {"url": LINK_PERIOD, "valueDuration": {
                             "value": link_days, "unit": "days",
                             "system": "http://unitsofmeasure.org", "code": "d"}}]
                item["extension"] = exts
            mark(item.get("item", []))

    mark(q.get("item", []))
    return q


def _period(item: Mapping[str, Any]) -> timedelta | None:
    for ext in item.get("extension", []):
        if ext.get("url") == LINK_PERIOD:
            d = ext["valueDuration"]
            return float(d["value"]) * DURATION_UNITS[str(d.get("code", "d"))]
    return None


def _codes(item: Mapping[str, Any]) -> set[tuple[str, str]]:
    return {(str(c.get("system")), str(c.get("code"))) for c in item.get("code", [])}


def _answer_from(item: Mapping[str, Any], obs: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = item.get("type")
    if kind == "boolean" and "valueBoolean" in obs:
        return {"valueBoolean": obs["valueBoolean"]}
    q = obs.get("valueQuantity")
    if q is not None and "value" in q:
        if kind == "integer":
            return {"valueInteger": round(float(q["value"]))}
        if kind == "decimal":
            return {"valueDecimal": float(q["value"])}
        if kind == "quantity":
            return {"valueQuantity": dict(q)}
    if kind == "integer" and "valueInteger" in obs:
        return {"valueInteger": obs["valueInteger"]}
    if kind == "choice" and "valueCodeableConcept" in obs:
        offered = {o["valueCoding"]["code"]: o["valueCoding"]
                   for o in item.get("answerOption", []) if "valueCoding" in o}
        for c in obs["valueCodeableConcept"].get("coding", []):
            if c.get("code") in offered:
                return {"valueCoding": offered[c["code"]]}
    if kind in ("string", "text") and "valueString" in obs:
        return {"valueString": obs["valueString"]}
    return None


def populate(questionnaire: Mapping[str, Any], subject: Mapping[str, Any],
             observations: Sequence[Mapping[str, Any]], *, now: datetime) -> dict[str, Any]:
    """`$populate`: an in-progress QuestionnaireResponse pre-filled from observations."""
    def matches(item: Mapping[str, Any], since: datetime) -> list[Mapping[str, Any]]:
        codes = _codes(item)
        hits = []
        for o in observations:
            if o.get("status") not in USABLE_STATUS or "effectiveDateTime" not in o:
                continue
            when = datetime.fromisoformat(str(o["effectiveDateTime"]))
            if when < since or when > now:
                continue
            if codes & {(str(c.get("system")), str(c.get("code")))
                        for c in o.get("code", {}).get("coding", [])}:
                hits.append(o)
        return sorted(hits, key=lambda o: str(o["effectiveDateTime"]), reverse=True)

    def fill(items: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        out = []
        for item in items:
            node: dict[str, Any] = {"linkId": item["linkId"]}
            if item.get("text"):
                node["text"] = item["text"]
            if item.get("item"):
                children = fill(item["item"])
                if children:
                    node["item"] = children
                    out.append(node)
                continue
            period = _period(item)
            if period is None or not item.get("code"):
                continue
            for o in matches(item, now - period):
                answer = _answer_from(item, o)
                if answer is not None:
                    node["answer"] = [answer]
                    out.append(node)
                    break
        return out

    body = {"resourceType": "QuestionnaireResponse", "status": "in-progress",
            "questionnaire": questionnaire["url"], "subject": dict(subject),
            "authored": now.isoformat(), "item": fill(questionnaire.get("item", []))}
    if not body["item"]:
        del body["item"]
    return dict(QuestionnaireResponse.model_validate(body).model_dump(mode="json",
                                                                       exclude_none=True))


def _value(answer: Mapping[str, Any]) -> dict[str, Any] | None:
    if "valueBoolean" in answer:
        return {"valueBoolean": answer["valueBoolean"]}
    if "valueInteger" in answer:
        return {"valueInteger": answer["valueInteger"]}
    if "valueDecimal" in answer:
        return {"valueQuantity": {"value": answer["valueDecimal"]}}
    if "valueQuantity" in answer:
        return {"valueQuantity": answer["valueQuantity"]}
    if "valueCoding" in answer:
        c = answer["valueCoding"]
        return {"valueCodeableConcept": {"coding": [c], **({"text": c["display"]}
                                                           if c.get("display") else {})}}
    if "valueString" in answer:
        return {"valueString": answer["valueString"]}
    if "valueDate" in answer:
        return {"valueDateTime": answer["valueDate"]}
    if "valueDateTime" in answer:
        return {"valueDateTime": answer["valueDateTime"]}
    return None


def extract(questionnaire: Mapping[str, Any], response: Mapping[str, Any]) -> list[dict[str, Any]]:
    """`$extract`: Observations of the answered, extractable, coded questions."""
    if response.get("status") not in ("completed", "amended"):
        raise ValueError("only a completed response is extracted")
    definitions = {str(item["linkId"]): (item, flag)
                   for item, flag in _items(questionnaire.get("item", []),
                                            _flag(questionnaire, False))}
    rid = str(response.get("id") or "qr")
    out = []

    def walk(items: Sequence[Mapping[str, Any]]) -> None:
        for answered in items:
            walk(answered.get("item", []))
            item, flag = definitions.get(str(answered["linkId"]), ({}, False))
            if not flag or not item.get("code"):
                continue
            for n, answer in enumerate(answered.get("answer", [])):
                value = _value(answer)
                if value is None:
                    continue
                link = str(answered["linkId"]).replace("_", "-")
                body: dict[str, Any] = {
                    "resourceType": "Observation",
                    "id": f"{rid}-{link}-{n}"[:64].replace("_", "-"),
                    "status": "final", "category": [{"coding": [SURVEY]}],
                    "code": {"coding": list(item["code"]), "text": item.get("text")},
                    "subject": response["subject"],
                    "derivedFrom": [{"reference": f"QuestionnaireResponse/{rid}"}],
                    **value}
                if response.get("authored"):
                    body["effectiveDateTime"] = response["authored"]
                out.append(dict(Observation.model_validate(body).model_dump(
                    mode="json", exclude_none=True)))

    walk(response.get("item", []))
    return out


def render(questionnaire: Mapping[str, Any]) -> dict[str, Any]:
    """The renderer data: a flat item list with depth, in display order."""
    rows: list[dict[str, Any]] = []

    def walk(items: Sequence[Mapping[str, Any]], depth: int, parent: str | None) -> None:
        for item in items:
            row: dict[str, Any] = {"linkId": item["linkId"], "type": item["type"],
                                   "text": item.get("text", ""), "depth": depth,
                                   "parent": parent, "required": bool(item.get("required")),
                                   "readOnly": bool(item.get("readOnly"))}
            if item.get("prefix"):
                row["prefix"] = item["prefix"]
            if item.get("answerOption"):
                row["options"] = [{"code": o["valueCoding"]["code"],
                                   "display": o["valueCoding"].get("display",
                                                                   o["valueCoding"]["code"])}
                                  for o in item["answerOption"] if "valueCoding" in o]
            rows.append(row)
            walk(item.get("item", []), depth + 1, str(item["linkId"]))

    walk(questionnaire.get("item", []), 0, None)
    return {"id": questionnaire["id"], "url": questionnaire["url"],
            "title": questionnaire.get("title", ""), "version": questionnaire.get("version"),
            "items": rows}
