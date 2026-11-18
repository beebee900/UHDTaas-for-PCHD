"""FHIR R4 Questionnaires built from the kb (design 06, 6.3.1 `questionnaires/*.json`).

- `history-<pathway>`: one yes/no item per question-captured finding that an association
  links to a condition of the pathway, plus onset; linkId = finding id, code = SNOMED CT
- one questionnaire per `instrument.*` entry, with scored answer options
- `consent`, `preferences` and `check-in`: operational forms whose answers map onto the
  consent registry, the agency record and the daily follow-up

Answers to history items become findings by linkId; the BN reads them directly.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from atra.config import ROOT
from atra.contracts import PurposeOfUse
from atra.kb import KnowledgeBase

SNOMED = "http://snomed.info/sct"
LOINC = "http://loinc.org"
ORDINAL = "http://hl7.org/fhir/StructureDefinition/ordinalValue"
BASE = "https://atra.health/fhir/Questionnaire"
LOCALES = ("en", "ha", "ig", "yo", "pcm")
CHANNELS = ("app", "sms", "ussd", "voice")
PURPOSE_TEXT: Mapping[PurposeOfUse, str] = {
    PurposeOfUse.CARE: "Use my record for my care at this facility",
    PurposeOfUse.EMERGENCY: "Use my record in an emergency at any facility",
    PurposeOfUse.SELF_MANAGEMENT: "Use my twin to support me at home",
    PurposeOfUse.PUBLIC_HEALTH: "Share de-identified data for public health",
    PurposeOfUse.RESEARCH: "Share de-identified data for research",
    PurposeOfUse.OPERATIONS: "Use my data to run and improve the service",
}


def _q(qid: str, title: str, items: list[dict[str, Any]], **extra: Any) -> dict[str, Any]:
    return {"resourceType": "Questionnaire", "id": qid, "url": f"{BASE}/{qid}",
            "version": "1.0.0", "status": "active", "title": title, **extra, "item": items}


def _choice(link: str, text: str, options: Iterable[tuple[str, str]],
            **extra: Any) -> dict[str, Any]:
    return {"linkId": link, "text": text, "type": "choice", **extra,
            "answerOption": [{"valueCoding": {"code": c, "display": d}} for c, d in options]}


def history(kb: KnowledgeBase) -> dict[str, dict[str, Any]]:
    by_pathway: dict[str, list[str]] = {}
    for eid in kb.ids():
        if not eid.startswith("assoc."):
            continue
        content = kb.entry(eid).content()
        if "condition" not in content:
            continue
        pathway = kb.entry(content["condition"]).content()["pathway"]
        for f in content.get("findings", []):
            fid = f["finding"]
            if kb.entry(fid).content().get("capture") == "question":
                by_pathway.setdefault(pathway, [])
                if fid not in by_pathway[pathway]:
                    by_pathway[pathway].append(fid)
    out = {}
    for pathway, fids in sorted(by_pathway.items()):
        items: list[dict[str, Any]] = [{
            "linkId": "onset_days", "text": "How many days ago did this illness start?",
            "type": "integer", "required": True}]
        for fid in sorted(fids):
            finding = kb.entry(fid).content()
            items.append({"linkId": fid, "text": f"{finding['name']}?", "type": "boolean",
                          "code": [{"system": SNOMED, "code": str(finding["snomed"]),
                                    "display": finding["name"]}]})
        qid = f"history-{pathway.replace('_', '-')}"
        out[qid] = _q(qid, f"History: {pathway.replace('_', ' ')}", items)
    return out


def _options(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{"valueCoding": {"code": o["code"], "display": o["display"]},
             "extension": [{"url": ORDINAL, "valueDecimal": o["score"]}]} for o in options]


def _score_item(link: str, text: str, loinc: str | None) -> dict[str, Any]:
    item: dict[str, Any] = {"linkId": link, "text": text, "type": "decimal", "readOnly": True}
    if loinc:
        item["code"] = [{"system": LOINC, "code": str(loinc)}]
    return item


def instruments(kb: KnowledgeBase) -> dict[str, dict[str, Any]]:
    """Item-level `options` override the shared scale; `prefix` is shown before the item.

    An instrument has either one `total` or a list of `scores` over named items.
    """
    out = {}
    for eid in kb.ids():
        if not eid.startswith("instrument."):
            continue
        inst = kb.entry(eid).content()
        shared = _options(inst["options"])
        items = []
        for i in inst["items"]:
            item = {"linkId": i["id"], "text": i["text"], "type": "choice", "required": True,
                    "answerOption": _options(i["options"]) if "options" in i else shared}
            if "prefix" in i:
                item["prefix"] = i["prefix"]
            items.append(item)
        group = {"linkId": "items", "text": inst["stem"], "type": "group", "item": items}
        if "scores" in inst:
            scored = [_score_item(s["id"], s["title"], s.get("loinc")) for s in inst["scores"]]
        else:
            scored = [_score_item("total", "Total score", inst.get("loinc"))]
            scored[0]["type"] = "integer"
        qid = eid.removeprefix("instrument.")
        out[qid] = _q(qid, inst["title"], [group, *scored])
    return out


def score(inst: Mapping[str, Any], answers: Mapping[str, str]) -> dict[str, float]:
    """Scores of one completed instrument from answer codes by item id.

    Returns `total`, or one T-score per entry of `scores` with its standard error as
    `<id>.se`. Every item of a score must be answered.
    """
    def item_score(item: Mapping[str, Any]) -> float:
        code = answers[item["id"]]
        options = item.get("options", inst["options"])
        return float(next(o["score"] for o in options if o["code"] == code))

    by_id = {i["id"]: i for i in inst["items"]}
    if "scores" not in inst:
        return {"total": sum(item_score(i) for i in inst["items"])}
    out: dict[str, float] = {}
    for s in inst["scores"]:
        raw = int(sum(item_score(by_id[i]) for i in s["items"]))
        out[s["id"]] = float(s["t_score"][raw])
        out[f"{s['id']}.se"] = float(s["se"][raw])
    return out


def operational() -> dict[str, dict[str, Any]]:
    yes_no = (("yes", "Yes"), ("no", "No"))
    consent = _q("consent", "Consent to use my health data", [
        {"linkId": p.value, "text": text, "type": "boolean", "required": p is PurposeOfUse.CARE}
        for p, text in PURPOSE_TEXT.items()
    ] + [{"linkId": "proxy", "text": "Someone may decide for me if I cannot", "type": "group",
          "item": [{"linkId": "proxy.name", "text": "Name", "type": "string"},
                   {"linkId": "proxy.relationship", "text": "Relationship to me", "type": "string"},
                   {"linkId": "proxy.phone", "text": "Phone number", "type": "string"}]}])
    preferences = _q("preferences", "How I want my care", [
        _choice("language", "Language", ((code, code) for code in LOCALES), required=True),
        _choice("channel", "How should we reach you?", ((c, c) for c in CHANNELS), required=True),
        _choice("literacy", "How often do you need help reading health information?",
                (("never", "Never"), ("sometimes", "Sometimes"), ("often", "Often"))),
        {"linkId": "priorities", "text": "What matters most to you in treatment?", "type": "group",
         "item": [{"linkId": f"priority.{k}", "text": t, "type": "integer"} for k, t in (
             ("effectiveness", "That it works best"), ("cost", "That it costs less"),
             ("side_effects", "Fewer side effects"), ("travel", "Less travel to the clinic"),
             ("time", "Shorter treatment"))]},
        {"linkId": "budget_ngn", "text": "How much can you spend on this treatment (naira)?",
         "type": "integer"},
    ])
    check_in = _q("check-in", "Daily check-in", [
        _choice("overall", "How do you feel today compared with yesterday?",
                (("better", "Better"), ("same", "The same"), ("worse", "Worse")), required=True),
        _choice("took_medicines", "Did you take all your medicines today?", yes_no, required=True),
        {"linkId": "danger_signs", "text": "Do you have any of these now?", "type": "group",
         "item": [{"linkId": fid, "text": text, "type": "boolean"} for fid, text in (
             ("find.convulsions", "Fits or convulsions"),
             ("find.impaired_consciousness", "Very sleepy or hard to wake"),
             ("find.respiratory_distress", "Difficult or fast breathing"),
             ("find.bleeding", "Bleeding that will not stop"),
             ("find.vomiting", "Vomiting"))]},
        {"linkId": "comment", "text": "Anything else you want your care team to know?",
         "type": "text"},
    ])
    return {q["id"]: q for q in (consent, preferences, check_in)}


def build(kb_dir: Path = ROOT / "kb") -> dict[str, dict[str, Any]]:
    kb = KnowledgeBase(kb_dir)
    return {**history(kb), **instruments(kb), **operational()}


def write(kb_dir: Path = ROOT / "kb") -> list[Path]:
    out_dir = kb_dir / "questionnaires"
    out_dir.mkdir(exist_ok=True)
    paths = []
    for qid, q in build(kb_dir).items():
        path = out_dir / f"{qid}.json"
        path.write_text(json.dumps(q, indent=2, ensure_ascii=False) + "\n")
        paths.append(path)
    return paths
