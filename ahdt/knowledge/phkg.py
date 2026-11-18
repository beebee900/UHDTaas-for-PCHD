"""Personal Health Knowledge Graph builder (design 04, 4.4.1).

One subgraph per person. Person-specific nodes carry the `hdt_id` in their id and as a
property; `System` nodes are shared (`system:<twin>`, the ids the APDT clinical graph uses)
and every fact is `OWNED_BY` the twin that owns it. Observation nodes hold the latest
value per field, so a high-rate stream adds one node, not one per sample.

Facts arrive from `observation.ingested` events (Layer 3.1) and from the record writers
(`condition`, `medication`, `phenotype`, `document`).
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any

from ahdt.ingest.fields import FieldIndex, field_index
from ahdt.knowledge import queries as q
from ahdt.registry import Registry, load_registry
from atra.backends.base import EventBusBackend, GraphBackend
from atra.config import ROOT
from atra.connectors import DTKind
from atra.contracts import EventEnvelope
from atra.ids import instance_id
from atra.kb import KnowledgeBase

COMPONENT_SPLIT = re.compile(r",\s*|\s+and\s+|\s*\+\s*")


def system_id(kind: DTKind | str) -> str:
    return f"system:{kind.value if isinstance(kind, DTKind) else kind}"


def condition_id(hdt_id: str, system: str, code: str) -> str:
    return f"cond:{hdt_id}:{system}:{code}"


def medication_id(hdt_id: str, atc: str) -> str:
    return f"med:{hdt_id}:{atc}"


def observation_id(hdt_id: str, field: str) -> str:
    return f"obs:{hdt_id}:{field}"


def phenotype_id(hdt_id: str, hpo: str) -> str:
    return f"pheno:{hdt_id}:{hpo}"


class PHKG:
    def __init__(self, graph: GraphBackend, *, registry: Registry | None = None,
                 index: FieldIndex | None = None, kb: KnowledgeBase | None = None) -> None:
        self.graph = graph
        self.registry = registry or load_registry()
        self.index = index or field_index()
        self.kb = kb or KnowledgeBase(ROOT / "kb")

    async def _node(self, stmt: str, nid: str, props: Mapping[str, Any]) -> None:
        await self.graph.run(stmt, {"id": nid, "props": {**props, "id": nid}})

    async def _edge(self, stmt: str, a: str, b: str) -> None:
        await self.graph.run(stmt, {"a": a, "b": b})

    def primary_organ(self, kind: DTKind) -> str | None:
        twin = self.registry.get(kind)
        return twin.owns_instances[0] if twin and twin.owns_instances else None

    async def person(self, hdt_id: str) -> None:
        await self._node(q.MERGE_PERSON, hdt_id, {"hdt_id": hdt_id})

    async def system(self, hdt_id: str, kind: DTKind) -> str:
        sid = system_id(kind)
        twin = self.registry.get(kind)
        await self._node(q.MERGE_SYSTEM, sid, {"kind": kind.value,
                                               "name": twin.name if twin else kind.value})
        await self.person(hdt_id)
        await self._edge(q.HAS_SYSTEM, hdt_id, sid)
        return sid

    async def organ(self, hdt_id: str, kind: DTKind) -> str | None:
        """The person's instance of the twin's primary organ, owned by the twin."""
        anatomy = self.primary_organ(kind)
        if anatomy is None:
            return None
        oid = instance_id(hdt_id, anatomy)
        sid = await self.system(hdt_id, kind)
        await self._node(q.MERGE_ORGAN, oid, {"hdt_id": hdt_id, "uberon": anatomy})
        await self._edge(q.HAS_ORGAN, hdt_id, oid)
        await self._edge(q.OWNED_BY_ORGAN, oid, sid)
        return oid

    async def observation(self, hdt_id: str, field: str, *, code: str, value: Any,
                          unit: str | None, effective_time: str, record_id: str) -> str:
        ref = self.index.by_name(field)
        if ref is None:
            raise KeyError(f"unknown field {field}")
        nid = observation_id(hdt_id, field)
        await self.person(hdt_id)
        await self._node(q.MERGE_OBSERVATION, nid, {
            "hdt_id": hdt_id, "field": field, "code": code, "value": value, "unit": unit,
            "time": effective_time, "record_id": record_id, "twin": ref.twin.value})
        await self._edge(q.HAS_OBSERVATION, hdt_id, nid)
        sid = await self.system(hdt_id, ref.twin)
        await self._edge(q.OWNED_BY_OBSERVATION, nid, sid)
        if (oid := await self.organ(hdt_id, ref.twin)) is not None:
            await self._edge(q.OBSERVED_IN, nid, oid)
        return nid

    async def condition(self, hdt_id: str, kb_id: str, *, status: str = "active") -> str:
        """A condition from `kb/conditions.yaml`, coded with SNOMED CT and ICD-11."""
        content = self.kb.entry(kb_id).content()
        system, code = ("snomed", content["snomed"]) if content.get("snomed") else (
            "icd11", content["icd11"])
        nid = condition_id(hdt_id, system, str(code))
        kind = DTKind(content["twin"])
        await self.person(hdt_id)
        await self._node(q.MERGE_CONDITION, nid, {
            "hdt_id": hdt_id, "kb_id": kb_id, "name": content["name"], "status": status,
            "snomed": content.get("snomed"), "icd11": content.get("icd11"), "twin": kind.value})
        await self._edge(q.HAS_CONDITION, hdt_id, nid)
        await self._edge(q.OWNED_BY_CONDITION, nid, await self.system(hdt_id, kind))
        if (oid := await self.organ(hdt_id, kind)) is not None:
            await self._edge(q.AFFECTS, nid, oid)
        return nid

    async def medication(self, hdt_id: str, atc: str, name: str, kind: DTKind) -> str:
        nid = medication_id(hdt_id, atc)
        await self.person(hdt_id)
        await self._node(q.MERGE_MEDICATION, nid, {"hdt_id": hdt_id, "atc": atc, "name": name,
                                                   "twin": kind.value})
        await self._edge(q.TAKES, hdt_id, nid)
        await self._edge(q.OWNED_BY_MEDICATION, nid, await self.system(hdt_id, kind))
        return nid

    def interaction_entries(self, medications: Sequence[tuple[str, str]]
                            ) -> list[tuple[str, str, str]]:
        """(ATC a, ATC b, kb entry id) for every `kb/interactions.yaml` drug-drug entry whose
        two sides name components of two of the given (ATC, name) medicines."""
        component: dict[str, str] = {}
        for atc, name in medications:
            for part in COMPONENT_SPLIT.split(name.lower()):
                if part:
                    component[part.strip()] = atc
        found: list[tuple[str, str, str]] = []
        for eid in self.kb.ids():
            if not eid.startswith("ix."):
                continue
            entry = self.kb.entry(eid).content()
            if entry.get("kind") != "drug_drug":
                continue
            sides = [[entry[k]] if isinstance(entry[k], str) else entry[k] for k in ("a", "b")]
            hits = [{component[n.lower()] for n in side if n.lower() in component}
                    for side in sides]
            found.extend((a, b, eid) for a in sorted(hits[0]) for b in sorted(hits[1])
                         if a != b)
        return found

    async def interactions(self, hdt_id: str, medications: Sequence[tuple[str, str]]) -> int:
        """`INTERACTS_WITH` edges, both directions, for every interacting pair."""
        found = self.interaction_entries(medications)
        for a, b, _ in found:
            await self._edge(q.INTERACTS_WITH, medication_id(hdt_id, a), medication_id(hdt_id, b))
            await self._edge(q.INTERACTS_WITH, medication_id(hdt_id, b), medication_id(hdt_id, a))
        return len(found)

    async def phenotype(self, hdt_id: str, hpo: str, label: str, kind: DTKind) -> str:
        nid = phenotype_id(hdt_id, hpo)
        await self.person(hdt_id)
        await self._node(q.MERGE_PHENOTYPE, nid, {"hdt_id": hdt_id, "hpo": hpo, "label": label})
        await self._edge(q.HAS_PHENOTYPE, hdt_id, nid)
        await self._edge(q.OWNED_BY_PHENOTYPE, nid, await self.system(hdt_id, kind))
        return nid

    def subscribe(self, events: EventBusBackend) -> None:
        async def handle(event: EventEnvelope) -> None:
            p = event.payload
            if event.hdt_id and "field" in p:
                await self.observation(event.hdt_id, p["field"], code=p["code"],
                                       value=p.get("value"), unit=p.get("unit"),
                                       effective_time=p["effective_time"],
                                       record_id=p["record_id"])

        events.subscribe("observation.ingested", handle)

    async def read(self, query_id: str, hdt_id: str, params: Mapping[str, Any] | None = None
                   ) -> list[dict[str, Any]]:
        """Run one allow-listed read query for a person."""
        stmt, needed = q.READ[query_id]
        args = {k: (params or {})[k] for k in needed}
        return await self.graph.run(stmt, {**args, "hdt_id": hdt_id})

    async def subgraph(self, hdt_id: str
                       ) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
        """The person's nodes (with `labels`) and edges, from allow-listed reads only."""
        nodes: dict[str, dict[str, Any]] = {}
        edges: list[tuple[str, str, str]] = []
        nodes[hdt_id] = {"id": hdt_id, "labels": ["Person"], "hdt_id": hdt_id}
        for query_id, label, rel in PERSON_LINKS:
            for row in await self.read(query_id, hdt_id):
                node = row["b"]
                nodes[node["id"]] = {**node, "labels": [label]}
                edges.append((hdt_id, rel, node["id"]))
        for nid, node in list(nodes.items()):
            if "Person" in node["labels"] or "System" in node["labels"]:
                continue
            for row in await self.read("fact.owner", hdt_id, {"id": nid}):
                edges.append((nid, "OWNED_BY", row["b"]["id"]))
            if "Condition" in node["labels"]:
                for row in await self.read("condition.organs", hdt_id, {"id": nid}):
                    edges.append((nid, "AFFECTS", row["b"]["id"]))
            if "Medication" in node["labels"]:
                for row in await self.read("medication.interactions", hdt_id, {"id": nid}):
                    edges.append((nid, "INTERACTS_WITH", row["b"]["id"]))
        return list(nodes.values()), sorted(set(edges))


PERSON_LINKS: tuple[tuple[str, str, str], ...] = (
    ("person.systems", "System", "HAS_SYSTEM"),
    ("person.organs", "Organ", "HAS_ORGAN"),
    ("person.conditions", "Condition", "HAS_CONDITION"),
    ("person.medications", "Medication", "TAKES"),
    ("person.phenotypes", "Phenotype", "HAS_PHENOTYPE"),
    ("person.observations", "Observation", "HAS_OBSERVATION"),
)
