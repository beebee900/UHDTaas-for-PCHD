"""`ahdt.data.graph_query`: questions about one person answered from the PHKG, the domain
graph and the guidelines, with citations (design 04, 4.4.3).

A question is matched to an intent; each intent runs allow-listed reads only. Citations
name PHKG node ids, Hetionet node IRIs or guideline sections, so every one resolves.

Modes:
- `graphrag`: PHKG and Hetionet intents only
- `chunkless`: guideline sections (BM25 over whole sections)
- `vector`: guideline passages from the dense index (built on the VM; absent in p0)
- `hybrid`: PHKG and Hetionet intents, else guideline sections by kb graph search
"""

from __future__ import annotations

import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ahdt.knowledge.hetionet import Hetionet
from ahdt.knowledge.phkg import PHKG

PATH_SEP = " > "
FIELD_WORDS: Mapping[str, str] = {
    "temperature": "temperature", "glucose": "glucose", "sugar": "glucose",
    "systolic": "sbp", "diastolic": "dbp", "creatinine": "creatinine",
    "haemoglobin": "hb", "hemoglobin": "hb", "weight": "weight", "heart rate": "heart_rate",
    "pulse": "heart_rate", "oxygen": "spo2", "spo2": "spo2", "potassium": "potassium",
}


class NoAnswer(LookupError):
    """No intent matched and the mode allows no guideline fallback."""


@dataclass
class Answer:
    answer: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    nodes: list[dict[str, Any]] = field(default_factory=list)
    edges: list[dict[str, Any]] = field(default_factory=list)

    def data(self) -> dict[str, Any]:
        out: dict[str, Any] = {"answer": self.answer, "citations": self.citations}
        if self.nodes:
            out["subgraph"] = {"nodes": self.nodes, "edges": self.edges}
        return out


def _cite(node: Mapping[str, Any], label: str) -> dict[str, Any]:
    return {"node_id": node["id"], "label": label}


def _name(node: Mapping[str, Any]) -> str:
    return str(node.get("name") or node.get("label") or node.get("field") or node["id"])


type Intent = Callable[[str, str], Awaitable[Answer | None]]


class GraphQA:
    def __init__(self, phkg: PHKG, *, hetionet: Hetionet | None = None,
                 guidelines: Any | None = None,
                 load_guidelines: Callable[[], Any] | None = None) -> None:
        """`load_guidelines` builds the guideline index on the first guideline question."""
        self.phkg = phkg
        self.hetionet = hetionet
        self.guidelines = guidelines
        self.load_guidelines = load_guidelines
        self.intents: list[tuple[re.Pattern[str], Intent]] = [
            (re.compile(r"interact"), self._interactions),
            (re.compile(r"\b(which|what) (twin|system)s?\b.*\bowns?\b|\bowned by\b"),
             self._owner),
            (re.compile(r"\borgans?\b.*\baffect|\baffect.*\borgans?\b"), self._organs),
            (re.compile(r"\b(drugs?|compounds?|medicines?)\b.*\b(treat|for)\b.*\b(disease|"
                        r"condition|hypertension|diabetes|asthma)"), self._domain_treats),
            (re.compile(r"\bsymptoms?\b.*\b(disease|present|of)\b.*\b(hypertension|diabetes|"
                        r"asthma)"), self._domain_symptoms),
            (re.compile(r"\b(latest|last|current|recent|most recent)\b"), self._observation),
            (re.compile(r"\b(medicines?|medications?|drugs?|taking|takes|prescribed)\b"),
             self._medications),
            (re.compile(r"\b(conditions?|diagnos\w*|problems?|diseases?)\b"), self._conditions),
            (re.compile(r"\b(phenotypes?|symptoms?|findings?|complain\w*)\b"), self._phenotypes),
            (re.compile(r"\b(twins|systems)\b"), self._systems),
        ]

    async def ask(self, hdt_id: str, question: str, mode: str = "hybrid") -> Answer:
        text = question.lower()
        if mode in ("graphrag", "hybrid"):
            for pattern, intent in self.intents:
                if pattern.search(text) and (found := await intent(hdt_id, text)) is not None:
                    return found
            if mode == "graphrag":
                raise NoAnswer("no knowledge-graph answer for this question")
        return await self._guidelines(question, "graph" if mode == "hybrid" else mode)

    async def _list(self, hdt_id: str, query_id: str, label: str, what: str) -> Answer | None:
        rows = await self.phkg.read(query_id, hdt_id)
        if not rows:
            return Answer(f"No {what} are recorded.", [_cite({"id": hdt_id}, "Person")])
        nodes = sorted((r["b"] for r in rows), key=_name)
        return Answer(f"Recorded {what}: " + "; ".join(_name(n) for n in nodes) + ".",
                      [_cite(n, label) for n in nodes],
                      [{"id": n["id"], "label": label} for n in nodes],
                      [{"from": hdt_id, "to": n["id"]} for n in nodes])

    async def _conditions(self, hdt_id: str, text: str) -> Answer | None:
        return await self._list(hdt_id, "person.conditions", "Condition", "conditions")

    async def _medications(self, hdt_id: str, text: str) -> Answer | None:
        return await self._list(hdt_id, "person.medications", "Medication", "medicines")

    async def _phenotypes(self, hdt_id: str, text: str) -> Answer | None:
        return await self._list(hdt_id, "person.phenotypes", "Phenotype", "phenotypes")

    async def _systems(self, hdt_id: str, text: str) -> Answer | None:
        return await self._list(hdt_id, "person.systems", "System", "twins")

    async def _interactions(self, hdt_id: str, text: str) -> Answer | None:
        meds = [r["b"] for r in await self.phkg.read("person.medications", hdt_id)]
        found = self.phkg.interaction_entries([(m["atc"], m["name"]) for m in meds])
        by_atc = {m["atc"]: m for m in meds}
        if not found:
            return Answer("No interactions between the recorded medicines are known.",
                          [_cite(m, "Medication") for m in meds])
        parts, cites = [], []
        for a, b, eid in found:
            effect = self.phkg.kb.entry(eid).content().get("effect", "")
            parts.append(f"{_name(by_atc[a])} with {_name(by_atc[b])}: {effect}".strip())
            cites += [_cite(by_atc[a], "Medication"), _cite(by_atc[b], "Medication"),
                      {"doc_id": f"kb:{eid}", "label": "kb interaction"}]
        return Answer(" ".join(parts), cites)

    async def _mentioned(self, hdt_id: str, text: str) -> list[tuple[dict[str, Any], str]]:
        found = []
        for query_id, label in (("person.conditions", "Condition"),
                                ("person.medications", "Medication"),
                                ("person.phenotypes", "Phenotype")):
            for row in await self.phkg.read(query_id, hdt_id):
                words = [w for w in re.split(r"\W+", _name(row["b"]).lower()) if len(w) > 3]
                if any(w in text for w in words):
                    found.append((row["b"], label))
        return found

    async def _owner(self, hdt_id: str, text: str) -> Answer | None:
        mentioned = await self._mentioned(hdt_id, text)
        if not mentioned:
            return None
        parts, cites = [], []
        for node, label in mentioned:
            for row in await self.phkg.read("fact.owner", hdt_id, {"id": node["id"]}):
                system = row["b"]
                parts.append(f"{_name(node)} is owned by the {system['name']}.")
                cites += [_cite(node, label), {"node_id": system["id"], "label": "System",
                                               "path": [node["id"], "OWNED_BY", system["id"]]}]
        return Answer(" ".join(parts), cites) if parts else None

    async def _organs(self, hdt_id: str, text: str) -> Answer | None:
        conditions = [n for n, label in await self._mentioned(hdt_id, text)
                      if label == "Condition"]
        if not conditions:
            conditions = [r["b"] for r in await self.phkg.read("person.conditions", hdt_id)]
        parts, cites = [], []
        for cond in conditions:
            for row in await self.phkg.read("condition.organs", hdt_id, {"id": cond["id"]}):
                organ = row["b"]
                parts.append(f"{_name(cond)} affects {organ['uberon']}.")
                cites += [_cite(cond, "Condition"),
                          {"node_id": organ["id"], "label": "Organ",
                           "path": [cond["id"], "AFFECTS", organ["id"]]}]
        return Answer(" ".join(parts), cites) if parts else None

    async def _observation(self, hdt_id: str, text: str) -> Answer | None:
        fields = [f for word, f in FIELD_WORDS.items() if word in text]
        if not fields:
            return None
        rows = await self.phkg.read("person.observation", hdt_id, {"field": fields[0]})
        if not rows:
            return Answer(f"No {fields[0]} value is recorded.", [_cite({"id": hdt_id}, "Person")])
        obs = rows[0]["b"]
        return Answer(f"Latest {obs['field']}: {obs['value']} {obs['unit']} at {obs['time']}.",
                      [_cite(obs, "Observation")])

    async def _domain(self, hdt_id: str, text: str, edge: str, kind: str, verb: str
                      ) -> Answer | None:
        if self.hetionet is None:
            return None
        for node, label in await self._mentioned(hdt_id, text) or [
                (r["b"], "Condition") for r in await self.phkg.read("person.conditions",
                                                                     hdt_id)]:
            if label != "Condition" or (disease := self.hetionet.disease(node["kb_id"])) is None:
                continue
            names = self.hetionet.neighbours(disease, edge, kind)
            if names:
                shown = ", ".join(names[:12])
                return Answer(f"Hetionet lists {len(names)} {kind.lower()} entries that {verb} "
                              f"{_name(node)}, including {shown}.",
                              [_cite(node, "Condition"), {"doc_id": disease,
                                                          "label": "Hetionet disease"}])
        return None

    async def _domain_treats(self, hdt_id: str, text: str) -> Answer | None:
        return await self._domain(hdt_id, text, "treats", "Compound", "treat")

    async def _domain_symptoms(self, hdt_id: str, text: str) -> Answer | None:
        return await self._domain(hdt_id, text, "presents", "Symptom", "present with")

    async def _guidelines(self, question: str, mode: str) -> Answer:
        if self.guidelines is None and self.load_guidelines is not None:
            self.guidelines = self.load_guidelines()
        if self.guidelines is None:
            raise NoAnswer("the guideline index is not loaded")
        hits = await self.guidelines.search(question, mode=mode, k=5)
        if not hits:
            raise NoAnswer(f"no guideline section matched in {mode} mode")
        cites = [{"doc_id": f"{h.citation.source}#{h.citation.section_id}",
                  "label": f"{h.citation.title} (p. {h.citation.page})",
                  "path": [h.citation.source, *h.citation.path.split(PATH_SEP)]} for h in hits]
        return Answer(hits[0].text[:600], cites)


async def seed(phkg: PHKG, hdt_id: str, facts: Mapping[str, Any]) -> None:
    """Load one persona's facts (the `evaluation/graph_query/personas.yaml` shape)."""
    from atra.connectors import DTKind

    for cond in facts.get("conditions", []):
        await phkg.condition(hdt_id, cond)
    meds: Sequence[Mapping[str, Any]] = facts.get("medications", [])
    for m in meds:
        await phkg.medication(hdt_id, m["atc"], m["name"], DTKind(m["twin"]))
    await phkg.interactions(hdt_id, [(m["atc"], m["name"]) for m in meds])
    for p in facts.get("phenotypes", []):
        await phkg.phenotype(hdt_id, p["hpo"], p["label"], DTKind(p["twin"]))
    for i, o in enumerate(facts.get("observations", [])):
        await phkg.observation(hdt_id, o["field"], code=o["code"], value=o["value"],
                               unit=o["unit"], effective_time="2026-10-01T08:00:00+00:00",
                               record_id=f"seed-{hdt_id}-{i}")
