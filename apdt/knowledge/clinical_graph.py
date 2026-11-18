"""Patient clinical graph (design 05, 5.4.2): one subgraph per episode, labels prefixed `Apdt`.

Episode nodes link to shared code concepts with `SAME_AS` (SNOMED CT, ICD-11, LOINC, ATC,
HPO). A concept carries the PHKG label of its kind and is `OWNED_BY` the AHDT system twin
from `kb/code_to_twin.csv`, so a diagnosis traverses to the owning twin in two hops.
Every statement stays inside the in-process Cypher subset (design 03, 3.12).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal

from apdt.knowledge.code_map import read as read_code_map
from atra.backends.base import GraphBackend
from atra.config import ROOT
from atra.kb import KnowledgeBase

type NodeKind = Literal["Symptom", "Finding", "Differential", "Test", "Result", "Diagnosis",
                        "Treatment", "Outcome", "PatientGoal"]
type EdgeKind = Literal["SUPPORTS", "REFUTES", "ORDERED_FOR", "CONFIRMS", "TREATS",
                        "RESULTED_IN", "ALIGNED_WITH", "SAME_AS"]
CONCEPT_LABEL: Mapping[str, str] = {"snomed": "Condition", "icd11": "Condition",
                                    "loinc": "Observation", "atc": "Medication",
                                    "hpo": "Phenotype"}


def concept_id(system: str, code: str) -> str:
    """Id of the shared PHKG concept node of a code; the AHDT uses the same ids."""
    return f"{system}:{code}"


class ClinicalGraph:
    def __init__(self, graph: GraphBackend, kb: KnowledgeBase | None = None,
                 code_map: Mapping[tuple[str, str], str] | None = None) -> None:
        self.graph = graph
        self.kb = kb or KnowledgeBase(ROOT / "kb")
        self.code_map = code_map if code_map is not None else read_code_map()
        self._associations: dict[str, set[str]] | None = None

    @staticmethod
    def node_id(episode_id: str, kind: NodeKind, key: str) -> str:
        return f"apdt:{episode_id}:{kind}:{key}"

    async def _node(self, label: str, nid: str, props: Mapping[str, Any]) -> None:
        await self.graph.run(f"MERGE (n:{label} {{id: $id}}) SET n += $props",
                             {"id": nid, "props": {**props, "id": nid}})

    async def _edge(self, a: str, rel: EdgeKind | str, b: str) -> None:
        await self.graph.run(f"MATCH (a {{id: $a}}), (b {{id: $b}}) MERGE (a)-[:{rel}]->(b)",
                             {"a": a, "b": b})

    async def _concept(self, system: str, code: str) -> str:
        cid = concept_id(system, code)
        await self._node(CONCEPT_LABEL[system], cid, {"system": system, "code": code})
        twin = self.code_map.get((system, code))
        if twin is not None:
            sid = f"system:{twin}"
            await self._node("System", sid, {"kind": twin})
            await self._edge(cid, "OWNED_BY", sid)
        return cid

    async def _add(self, episode_id: str, kind: NodeKind, key: str,
                   props: Mapping[str, Any], codes: Mapping[str, Any] | None = None) -> str:
        nid = self.node_id(episode_id, kind, key)
        await self._node(f"Apdt{kind}", nid, {"episode_id": episode_id, "key": key, **props})
        for system, code in (codes or {}).items():
            if code and system in CONCEPT_LABEL:
                await self._edge(nid, "SAME_AS", await self._concept(system, str(code)))
        return nid

    def _codes(self, entry_id: str, *systems: str) -> dict[str, Any]:
        content = self.kb.entry(entry_id).content()
        return {s: content.get(s) for s in systems}

    async def finding(self, episode_id: str, finding_id: str, *, present: bool = True,
                      source: str = "history") -> str:
        """A symptom (patient-reported) or finding (exam, measurement, lab) from findings.yaml."""
        content = self.kb.entry(finding_id).content()
        kind: NodeKind = "Symptom" if content.get("capture") == "question" else "Finding"
        nid = await self._add(episode_id, kind, finding_id,
                              {"name": content["name"], "present": present, "source": source},
                              self._codes(finding_id, "snomed", "hpo"))
        for diff in await self._episode_nodes(episode_id, "Differential"):
            await self._link_evidence(nid, finding_id, present, diff)
        return nid

    async def differential(self, episode_id: str, condition_id: str, probability: float) -> str:
        cond = self.kb.entry(condition_id).content()
        nid = await self._add(episode_id, "Differential", condition_id,
                              {"name": cond["name"], "probability": probability},
                              self._codes(condition_id, "snomed", "icd11"))
        node = {"id": nid, "key": condition_id}
        evidence_kinds: tuple[NodeKind, ...] = ("Symptom", "Finding")
        for kind in evidence_kinds:
            for f in await self._episode_nodes(episode_id, kind):
                await self._link_evidence(f["id"], f["key"], bool(f["present"]), node)
        return nid

    async def _link_evidence(self, finding_node: str, finding_id: str, present: bool,
                             differential: Mapping[str, Any]) -> None:
        if finding_id in self._associated(differential["key"]):
            await self._edge(finding_node, "SUPPORTS" if present else "REFUTES",
                             differential["id"])

    def _associated(self, condition_id: str) -> set[str]:
        if self._associations is None:
            self._associations = {}
            for eid in self.kb.ids():
                if eid.startswith("assoc."):
                    content = self.kb.entry(eid).content()
                    if "condition" in content:
                        self._associations.setdefault(content["condition"], set()).update(
                            f["finding"] for f in content.get("findings", []))
        return self._associations.get(condition_id, set())

    async def test(self, episode_id: str, test_id: str, *, for_conditions: Sequence[str]) -> str:
        test = self.kb.entry(test_id).content()
        nid = await self._add(episode_id, "Test", test_id, {"name": test["name"]},
                              self._codes(test_id, "loinc"))
        for cid in for_conditions:
            await self._edge(nid, "ORDERED_FOR", self.node_id(episode_id, "Differential", cid))
        return nid

    async def result(self, episode_id: str, test_id: str, *, value: Any,
                     supports: Sequence[str] = (), refutes: Sequence[str] = ()) -> str:
        nid = await self._add(episode_id, "Result", test_id, {"value": value},
                              self._codes(test_id, "loinc"))
        await self._edge(self.node_id(episode_id, "Test", test_id), "RESULTED_IN", nid)
        for cid in supports:
            await self._edge(nid, "SUPPORTS", self.node_id(episode_id, "Differential", cid))
        for cid in refutes:
            await self._edge(nid, "REFUTES", self.node_id(episode_id, "Differential", cid))
        return nid

    async def diagnosis(self, episode_id: str, condition_id: str, *,
                        confirmed_by: Sequence[str] = (), severity: str | None = None) -> str:
        cond = self.kb.entry(condition_id).content()
        nid = await self._add(episode_id, "Diagnosis", condition_id,
                              {"name": cond["name"], "severity": severity},
                              self._codes(condition_id, "snomed", "icd11"))
        for test_id in confirmed_by:
            await self._edge(self.node_id(episode_id, "Result", test_id), "CONFIRMS", nid)
        return nid

    async def treatment(self, episode_id: str, treatment_id: str, *,
                        goals: Sequence[str] = ()) -> str:
        tx = self.kb.entry(treatment_id).content()
        regimens = tx["regimen"] if isinstance(tx["regimen"], list) else [tx["regimen"]]
        nid = await self._add(episode_id, "Treatment", treatment_id,
                              {"regimen": regimens, "condition": tx["condition"]})
        for reg in regimens:
            atc = self.kb.entry(reg).content().get("atc")
            if atc:
                await self._edge(nid, "SAME_AS", await self._concept("atc", str(atc)))
        await self._edge(nid, "TREATS", self.node_id(episode_id, "Diagnosis", tx["condition"]))
        for goal in goals:
            await self._edge(nid, "ALIGNED_WITH", self.node_id(episode_id, "PatientGoal", goal))
        return nid

    async def goal(self, episode_id: str, key: str, text: str) -> str:
        return await self._add(episode_id, "PatientGoal", key, {"text": text})

    async def outcome(self, episode_id: str, treatment_id: str, key: str, status: str) -> str:
        nid = await self._add(episode_id, "Outcome", key, {"status": status})
        await self._edge(self.node_id(episode_id, "Treatment", treatment_id), "RESULTED_IN", nid)
        return nid

    async def _episode_nodes(self, episode_id: str, kind: NodeKind) -> list[dict[str, Any]]:
        rows = await self.graph.run(f"MATCH (n:Apdt{kind} {{episode_id: $e}}) RETURN n",
                                    {"e": episode_id})
        return [r["n"] for r in rows]

    async def evidence(self, episode_id: str, condition_id: str) -> dict[str, list[str]]:
        """Node keys that support or refute a differential."""
        did = self.node_id(episode_id, "Differential", condition_id)
        out: dict[str, list[str]] = {"SUPPORTS": [], "REFUTES": []}
        kinds: tuple[NodeKind, ...] = ("Symptom", "Finding", "Result")
        for kind in kinds:
            for node in await self._episode_nodes(episode_id, kind):
                for row in await self.graph.run(
                        "MATCH (a)-[r]->(b) WHERE a.id = $id RETURN type(r) AS rel, b",
                        {"id": node["id"]}):
                    if row["b"]["id"] == did and row["rel"] in out:
                        out[row["rel"]].append(node["key"])
        return out

    async def owning_twins(self, episode_id: str, kind: NodeKind, key: str) -> list[str]:
        """AHDT twins reached from an episode node through SAME_AS → OWNED_BY."""
        rows = await self.graph.run(
            "MATCH (a {id: $id})-[:SAME_AS*1..1]->(c) RETURN c",
            {"id": self.node_id(episode_id, kind, key)})
        twins: list[str] = []
        for row in rows:
            for hop in await self.graph.run(
                    "MATCH (a)-[r:OWNED_BY]->(s) WHERE a.id = $id RETURN s",
                    {"id": row["c"]["id"]}):
                if hop["s"]["kind"] not in twins:
                    twins.append(hop["s"]["kind"])
        return twins
