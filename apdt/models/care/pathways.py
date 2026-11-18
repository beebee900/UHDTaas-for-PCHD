"""Care pathways: `$apply` of a PlanDefinition and conformance checking (design 05, 5.5.3).

`apply` turns a kb PlanDefinition (`kb/plandefinitions`) into a draft FHIR CarePlan and Tasks
for one patient. The severity group and the option come from the treatment rule engine, so
the plan agrees with the options the clinician sees. `conformance` replays the executed task
log against the pathway's BPMN model (`kb/pathways`) with pm4py token replay and reports the
steps that deviate.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from apdt.knowledge.pathways import BASE, KB_EXT, TASK_NAMES
from apdt.models.context import Observations, Patient, kb
from apdt.models.treatment.options import Option, options_for
from atra.config import get_settings


def plan_definition(condition: str) -> dict[str, Any]:
    name = condition.removeprefix("cond.").replace("_", "-")
    path = get_settings().kb_dir / "plandefinitions" / f"{name}.json"
    if not path.exists():
        raise KeyError(f"no PlanDefinition for {condition}")
    plan: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return plan


@dataclass
class AppliedPlan:
    care_plan: dict[str, Any]
    tasks: list[dict[str, Any]]
    option: Option | None
    severity: str | None
    notes: list[str] = field(default_factory=list)


def _task(task_id: str, plan_id: str, hdt_id: str, description: str, when: datetime,
          *, focus: str | None = None, code: str | None = None) -> dict[str, Any]:
    task: dict[str, Any] = {
        "resourceType": "Task", "id": task_id, "status": "draft", "intent": "proposal",
        "description": description, "authoredOn": when.isoformat(),
        "for": {"reference": f"Patient/{hdt_id}"},
        "basedOn": [{"reference": f"CarePlan/{plan_id}"}]}
    if focus:
        task["focus"] = {"display": focus}
    if code:
        task["code"] = {"text": code}
    return task


def apply(condition: str, patient: Patient, obs: Observations, hdt_id: str,
          *, episode_id: str | None = None, when: datetime | None = None) -> AppliedPlan:
    """`PlanDefinition/$apply` for one condition: a draft CarePlan and its Tasks."""
    when = when or datetime.now(UTC)
    plan = plan_definition(condition)
    option_set = options_for(condition, patient, obs, hdt_id)
    option = option_set.eligible[0] if option_set.eligible else None
    plan_id = f"careplan-{plan['id']}-{hdt_id}"
    activities: list[dict[str, Any]] = []
    tasks: list[dict[str, Any]] = []
    notes: list[str] = []
    for action in plan["action"]:
        if action["id"] == "grade":
            tasks.append(_task(f"{plan_id}-grade", plan_id, hdt_id, "Grade severity",
                               when, code=f"severity: {option_set.severity}"))
        elif action["id"] == "treat":
            if option is None:
                notes.append("no eligible option; refer to the clinician")
                continue
            names = [d.dose_id for d in option.doses] or [option.drug_class or option.option_id]
            activities.append({"detail": {
                "kind": "MedicationRequest", "status": "not-started",
                "description": ", ".join(names),
                "extension": [{"url": KB_EXT, "valueString": option.option_id}]}})
            tasks.append(_task(f"{plan_id}-treat", plan_id, hdt_id,
                               f"Prescribe: {', '.join(names)}", when, focus=option.option_id))
        else:
            activities.append({"detail": {"kind": "Task", "status": "not-started",
                                          "description": action["title"]}})
            tasks.append(_task(f"{plan_id}-{action['id']}", plan_id, hdt_id, action["title"],
                               when))
    care_plan: dict[str, Any] = {
        "resourceType": "CarePlan", "id": plan_id, "status": "draft", "intent": "proposal",
        "title": plan["title"], "subject": {"reference": f"Patient/{hdt_id}"},
        "created": when.isoformat(), "instantiatesCanonical": [plan["url"]],
        "activity": activities}
    if episode_id:
        care_plan["encounter"] = {"reference": f"EpisodeOfCare/{episode_id}"}
    return AppliedPlan(care_plan, tasks, option, option_set.severity, notes)


@dataclass(frozen=True)
class Deviation:
    case_id: str
    fit: bool
    missing_tokens: int
    remaining_tokens: int
    problem_steps: tuple[str, ...]


@dataclass(frozen=True)
class Conformance:
    pathway: str
    fitness: float
    deviations: tuple[Deviation, ...]

    @property
    def conformant(self) -> bool:
        return all(d.fit for d in self.deviations)


def _bpmn_path(pathway: str) -> Path:
    return get_settings().kb_dir / "pathways" / f"{pathway}.bpmn"


def conformance(pathway: str, executed: Mapping[str, Sequence[tuple[str, datetime]]]
                ) -> Conformance:
    """Token-replay conformance of executed task logs. `executed` maps a case id to its
    (task id, time) events; task ids are those of `apdt.knowledge.pathways.TASK_NAMES`."""
    import pandas as pd
    import pm4py

    bpmn = pm4py.read_bpmn(str(_bpmn_path(pathway)))
    net, im, fm = pm4py.convert_to_petri_net(bpmn)
    def frame(case: str, events: Sequence[tuple[str, datetime]]) -> Any:
        rows = [{"case:concept:name": case, "concept:name": TASK_NAMES[task],
                 "time:timestamp": pd.Timestamp(t)} for task, t in events]
        return pm4py.format_dataframe(pd.DataFrame(rows), case_id="case:concept:name",
                                      activity_key="concept:name",
                                      timestamp_key="time:timestamp")

    out = []
    fitness = []
    for case, events in executed.items():
        log = frame(case, events)
        d = pm4py.conformance_diagnostics_token_based_replay(log, net, im, fm)[0]
        problems = tuple(sorted(str(t.label) for t in d.get("transitions_with_problems", [])
                                if t.label))
        out.append(Deviation(case, bool(d["trace_is_fit"]), int(d["missing_tokens"]),
                             int(d["remaining_tokens"]), problems))
        fitness.append(float(d["trace_fitness"]))
    return Conformance(pathway, float(sum(fitness) / len(fitness)) if fitness else 1.0,
                       tuple(out))


def pathway_of(condition: str) -> str:
    return str(kb().entry(condition).content()["pathway"])


__all__ = ["BASE", "AppliedPlan", "Conformance", "Deviation", "apply", "conformance",
           "pathway_of", "plan_definition"]
