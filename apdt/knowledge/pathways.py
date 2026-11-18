"""Care pathways built from the kb (design 05, 5.5 "Care pathway and plan").

- `kb/plandefinitions/<condition>.json`: FHIR R4 PlanDefinition per condition. It grades
  severity, then offers one treatment group per severity level whose options are the
  `tx.*` entries (eligibility and exclusions travel as extensions the rule engine reads),
  then monitoring by the early-warning score and a daily check-in.
- `kb/pathways/<pathway>.bpmn`: BPMN 2.0 process per pathway. pm4py replays executed
  task logs against it for conformance.
"""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from atra.config import ROOT
from atra.kb import KnowledgeBase

BASE = "https://atra.health/fhir"
KB_EXT = f"{BASE}/StructureDefinition/kb-entry"
ELIGIBILITY_EXT = f"{BASE}/StructureDefinition/eligibility"
EXCLUSIONS_EXT = f"{BASE}/StructureDefinition/exclusions"
PREFERENCE_EXT = f"{BASE}/StructureDefinition/preference"
PREFERENCE_ORDER = ("pre_referral", "first_line", "second_line", "alternative")

# BPMN tasks in order; `treat` sits behind an exclusive gateway on severity.
STEPS = (("register", "Register and consent"), ("triage", "Triage with early-warning score"),
         ("history", "Take history"), ("examine", "Examine"), ("test", "Order and read tests"),
         ("diagnose", "Confirm diagnosis and severity"))
TAIL = (("follow_up", "Monitor and check in"), ("discharge", "Discharge or close episode"))
BRANCHES = (("treat", "Treat at this facility"), ("refer", "Stabilise and refer"))
# Task id → BPMN task name. pm4py labels transitions by name, so event logs use these.
TASK_NAMES = dict((*STEPS, *BRANCHES, *TAIL))


def _severities(value: Any) -> list[str]:
    if value is None:
        return ["any"]
    return [str(v) for v in value] if isinstance(value, list) else [str(value)]


def _regimen(regimen: str | list[str]) -> dict[str, Any]:
    """A single regimen is the action's definition; a combination is an `all` group."""
    regs = regimen if isinstance(regimen, list) else [regimen]
    titles = [r.removeprefix("dose.").replace("_", " ") for r in regs]
    if len(regs) == 1:
        return {"title": titles[0], "definitionCanonical": f"{BASE}/ActivityDefinition/{regs[0]}"}
    return {"title": " + ".join(titles), "selectionBehavior": "all",
            "action": [{"id": r, "title": t,
                        "definitionCanonical": f"{BASE}/ActivityDefinition/{r}"}
                       for r, t in zip(regs, titles, strict=True)]}


def _options(kb: KnowledgeBase, cond_id: str) -> Iterator[dict[str, Any]]:
    for eid in kb.ids():
        if eid.startswith("tx."):
            content = kb.entry(eid).content()
            if content.get("condition") == cond_id:
                yield {"id": eid, **content}


def plan_definition(kb: KnowledgeBase, cond_id: str) -> dict[str, Any] | None:
    options = list(_options(kb, cond_id))
    if not options:
        return None
    cond = kb.entry(cond_id).content()
    groups: dict[str, list[dict[str, Any]]] = {}
    for opt in options:
        for sev in _severities(opt.get("severity")):
            groups.setdefault(sev, []).append(opt)
    treat = []
    for sev, opts in groups.items():
        opts.sort(key=lambda o: PREFERENCE_ORDER.index(o.get("preference", "alternative")))
        treat.append({
            "id": f"treat-{sev}", "title": f"Treat ({sev.replace('_', ' ')})",
            "condition": [{"kind": "applicability", "expression": {
                "language": "text/fhirpath", "expression": f"%severity = '{sev}'"
                if sev != "any" else "true"}}],
            "selectionBehavior": "exactly-one",
            "action": [{
                "id": o["id"], **_regimen(o["regimen"]),
                "extension": [{"url": KB_EXT, "valueString": o["id"]},
                              {"url": PREFERENCE_EXT,
                               "valueCode": o.get("preference", "alternative")},
                              {"url": ELIGIBILITY_EXT,
                               "valueString": json.dumps(o.get("eligibility", {}), sort_keys=True)},
                              *([{"url": EXCLUSIONS_EXT,
                                  "valueString": json.dumps(o["exclusions"])}]
                                if o.get("exclusions") else [])],
            } for o in opts if o.get("regimen")],
        })
    actions: list[dict[str, Any]] = []
    if cond.get("severity_rule"):
        actions.append({"id": "grade", "title": "Grade severity",
                        "extension": [{"url": KB_EXT, "valueString": cond["severity_rule"]}]})
    actions.append({"id": "treat", "title": "Choose treatment", "selectionBehavior": "exactly-one",
                    "action": [g for g in treat if g["action"]]})
    actions.append({"id": "monitor", "title": "Monitor with the early-warning score",
                    "extension": [{"url": KB_EXT, "valueString": "news2.monitoring"}]})
    actions.append({"id": "check-in", "title": "Daily check-in",
                    "definitionCanonical": f"{BASE}/Questionnaire/check-in"})
    name = cond_id.removeprefix("cond.")
    return {
        "resourceType": "PlanDefinition", "id": name.replace("_", "-"),
        "url": f"{BASE}/PlanDefinition/{name}", "version": "1.0.0", "name": name,
        "title": cond["name"], "type": {"coding": [{
            "system": "http://terminology.hl7.org/CodeSystem/plan-definition-type",
            "code": "clinical-protocol"}]},
        "status": "active",
        "useContext": [{"code": {"system": "http://terminology.hl7.org/CodeSystem/usage-context-type",
                                 "code": "focus"},
                        "valueCodeableConcept": {"coding": [{"system": "http://snomed.info/sct",
                                                             "code": str(cond["snomed"])}]}}],
        "extension": [{"url": KB_EXT, "valueString": cond_id}],
        "action": actions,
    }


def bpmn(pathway: str) -> str:
    pid = f"pathway_{pathway}"
    tasks = [*STEPS, *BRANCHES, *TAIL]
    nodes = ['    <bpmn:startEvent id="start" name="Patient arrives"/>']
    nodes += [f'    <bpmn:task id="{t}" name="{escape(n)}"/>' for t, n in tasks]
    nodes += ['    <bpmn:exclusiveGateway id="severity" name="Severe?"/>',
              '    <bpmn:exclusiveGateway id="join"/>',
              '    <bpmn:endEvent id="end" name="Episode closed"/>']
    chain = ["start", *[t for t, _ in STEPS], "severity"]
    flows = list(itertools.pairwise(chain))
    flows += [("severity", "treat"), ("severity", "refer"), ("treat", "join"), ("refer", "join"),
              ("join", TAIL[0][0]), (TAIL[0][0], TAIL[1][0]), (TAIL[1][0], "end")]
    edges = [f'    <bpmn:sequenceFlow id="f{i}" sourceRef="{a}" targetRef="{b}"/>'
             for i, (a, b) in enumerate(flows)]
    return "\n".join([
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL" '
        f'id="defs_{pathway}" targetNamespace="{BASE}/pathways">',
        f'  <bpmn:process id="{pid}" name="{escape(pathway.replace("_", " "))}" '
        'isExecutable="false">',
        *nodes, *edges, "  </bpmn:process>", "</bpmn:definitions>", ""])


def write(kb_dir: Path = ROOT / "kb") -> list[Path]:
    kb = KnowledgeBase(kb_dir)
    paths: list[Path] = []
    pd_dir, bp_dir = kb_dir / "plandefinitions", kb_dir / "pathways"
    pd_dir.mkdir(exist_ok=True)
    bp_dir.mkdir(exist_ok=True)
    pathways: set[str] = set()
    for cid in kb.ids():
        if not cid.startswith("cond."):
            continue
        pathways.add(kb.entry(cid).content()["pathway"])
        pd = plan_definition(kb, cid)
        if pd is not None:
            path = pd_dir / f"{pd['id']}.json"
            path.write_text(json.dumps(pd, indent=2, ensure_ascii=False) + "\n")
            paths.append(path)
    for pathway in sorted(pathways):
        path = bp_dir / f"{pathway}.bpmn"
        path.write_text(bpmn(pathway))
        paths.append(path)
    return paths
