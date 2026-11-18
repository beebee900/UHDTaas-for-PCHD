"""Cross-model causal explanation graph (design 04, 4.6.2).

The recorder writes what happened into W3C PROV: observations, connector messages (written
by the connectors), model runs with the entities each run used, and the explainer
attributions. The builder reads the PROV document only. For an `output_id` it follows

    output -> model run -> inputs (observations, connector messages)
    connector message -> the upstream output it carried

and gives each edge the attribution of that input where an explainer produced one, and 1
otherwise. Nothing in the graph is written by hand: a different history in the provenance
gives a different graph.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import prov.model as pm

from atra import contracts as c
from atra.backends.base import GraphBackend
from atra.provenance import ProvenanceStore

NS = "atra:"
EXPLAINS = "explains"
ATTRIBUTIONS = "attributions"


def _qn(local: str) -> str:
    return local if local.startswith(NS) else f"{NS}{local}"


class ProvenanceRecorder:
    """Writes model runs and attributions next to the observations and messages that the
    ingest pipeline and the connectors already record."""

    def __init__(self, store: ProvenanceStore) -> None:
        self.store = store

    def observation(self, obs_id: str, *, hdt_id: str, field_name: str, twin: str,
                    **attrs: Any) -> str:
        return self.store.entity(obs_id, "observation", hdt_id=hdt_id, field=field_name,
                                 twin=twin, **attrs)

    def model_run(self, output_id: str, model_id: str, version: str, *, hdt_id: str,
                  used: Sequence[str], twin: str | None = None) -> str:
        """Record that the output `output_id` came from one run of the model that used the
        entities `used` (observations and connector messages)."""
        entity = self.store.entity(output_id, "model_output", model_id=model_id,
                                   version=version, hdt_id=hdt_id,
                                   **({"twin": twin} if twin else {}))
        self.store.activity("predict", used=list(used), generated=[entity], model_id=model_id,
                            version=version)
        return entity

    def link_message(self, message_id: str, upstream: str) -> None:
        """The connector message `message_id` (its `prov_id`) carried `upstream`: a model
        output or an observation."""
        self.store.derived(message_id, upstream)

    def attributions(self, output_id: str, weights: Mapping[str, float], explainer: str) -> str:
        """Record an explainer's attribution of the output to its inputs (entity ids)."""
        eid = self.store.entity(f"expl-{_local(output_id)}-{_slug(explainer)}", "explanation",
                                **{EXPLAINS: _qn(output_id), "explainer": explainer,
                                   ATTRIBUTIONS: {_qn(k): float(v) for k, v in weights.items()}})
        self.store.activity("explain", used=[output_id], generated=[eid], explainer=explainer)
        return eid


def _local(qname: str) -> str:
    return qname.removeprefix(NS)


def _slug(text: str) -> str:
    return "".join(ch if ch.isalnum() else "-" for ch in text)


@dataclass
class Node:
    id: str
    kind: str
    label: str
    attrs: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    source: str
    target: str
    weight: float
    explained: bool = False


@dataclass
class CausalGraph:
    root: str
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)

    def to_contract(self) -> c.CausalGraphData:
        return c.CausalGraphData(
            nodes=[c.GraphNode(id=n.id, kind=n.kind, label=n.label)
                   for n in self.nodes.values()],
            edges=[c.GraphEdge.model_validate({"from": e.source, "to": e.target,
                                               "weight": e.weight}) for e in self.edges])

    def twins(self) -> set[str]:
        return {str(n.attrs["twin"]) for n in self.nodes.values() if "twin" in n.attrs}

    def inputs_of(self, node_id: str) -> list[Edge]:
        return [e for e in self.edges if e.target == node_id]


def _value(v: Any) -> Any:
    if isinstance(v, pm.Literal):
        v = v.value
    if isinstance(v, str) and v[:1] in "{[":
        try:
            return json.loads(v)
        except ValueError:
            return v
    return v


class _Index:
    """Lookups over a PROV document."""

    def __init__(self, doc: pm.ProvDocument) -> None:
        self.attrs: dict[str, dict[str, Any]] = {}
        self.generated_by: dict[str, list[str]] = {}
        self.used: dict[str, list[str]] = {}
        self.derived_from: dict[str, list[str]] = {}
        for rec in doc.get_records():
            if isinstance(rec, pm.ProvEntity | pm.ProvActivity):
                bucket = self.attrs.setdefault(str(rec.identifier), {})
                for key, val in rec.attributes:
                    bucket[str(key).removeprefix(NS)] = _value(val)
            elif isinstance(rec, pm.ProvGeneration):
                f = {str(k): str(v) for k, v in rec.formal_attributes if v is not None}
                self.generated_by.setdefault(f["prov:entity"], []).append(f["prov:activity"])
            elif isinstance(rec, pm.ProvUsage):
                f = {str(k): str(v) for k, v in rec.formal_attributes if v is not None}
                self.used.setdefault(f["prov:activity"], []).append(f["prov:entity"])
            elif isinstance(rec, pm.ProvDerivation):
                f = {str(k): str(v) for k, v in rec.formal_attributes if v is not None}
                self.derived_from.setdefault(f["prov:generatedEntity"], []).append(
                    f["prov:usedEntity"])

    def kind(self, entity: str) -> str:
        return str(self.attrs.get(entity, {}).get("kind", ""))

    def attributions(self, output: str) -> dict[str, float]:
        merged: dict[str, float] = {}
        for attrs in self.attrs.values():
            if attrs.get("kind") == "explanation" and attrs.get(EXPLAINS) == output:
                merged.update({k: float(v) for k, v in dict(attrs.get(ATTRIBUTIONS, {})).items()})
        return merged


def _label(kind: str, attrs: Mapping[str, Any], ident: str) -> str:
    if kind == "model_output":
        return f"{attrs.get('model_id', ident)} {attrs.get('version', '')}".strip()
    if kind == "message":
        return f"{attrs.get('contract', 'message')} from {_short(attrs.get('source'))}"
    return f"{attrs.get('field', ident)}"


def _short(uri: Any) -> str:
    parts = str(uri or "").split("/")
    return parts[-2] if len(parts) >= 2 else str(uri or "")


def _twin_of_uri(uri: Any) -> str | None:
    parts = str(uri or "").split("/")
    return parts[-2] if len(parts) >= 3 else None


class CausalGraphBuilder:
    """Builds the graph of an output from a PROV document or its JSON serialisation."""

    def __init__(self, source: ProvenanceStore | pm.ProvDocument | str) -> None:
        if isinstance(source, ProvenanceStore):
            doc = source.doc
        elif isinstance(source, str):
            doc = pm.ProvDocument.deserialize(content=source, format="json")
        else:
            doc = source
        self.index = _Index(doc)

    def build(self, output_id: str, *, max_depth: int = 8) -> CausalGraph:
        root = _qn(output_id)
        if root not in self.index.attrs:
            raise KeyError(f"no provenance for output {output_id}")
        graph = CausalGraph(root=root)
        self._output(graph, root, max_depth)
        return graph

    def _add(self, graph: CausalGraph, ident: str) -> Node:
        if ident not in graph.nodes:
            attrs = dict(self.index.attrs.get(ident, {}))
            kind = self.index.kind(ident)
            if kind == "message" and "twin" not in attrs:
                twin = _twin_of_uri(attrs.get("source"))
                if twin:
                    attrs["twin"] = twin
            graph.nodes[ident] = Node(ident, "model" if kind == "model_output" else kind,
                                      _label(kind, attrs, ident), attrs)
        return graph.nodes[ident]

    def _output(self, graph: CausalGraph, output: str, depth: int) -> None:
        self._add(graph, output)
        weights = self.index.attributions(output)
        for activity in self.index.generated_by.get(output, []):
            for used in self.index.used.get(activity, []):
                if self.index.kind(used) not in ("observation", "message", "model_output"):
                    continue
                self._add(graph, used)
                explained = used in weights
                graph.edges.append(Edge(used, output, weights.get(used, 1.0), explained))
                if self.index.kind(used) == "message" and depth > 0:
                    self._message(graph, used, depth - 1)
                elif self.index.kind(used) == "model_output" and depth > 0:
                    self._output(graph, used, depth - 1)

    def _message(self, graph: CausalGraph, message: str, depth: int) -> None:
        for upstream in self.index.derived_from.get(message, []):
            kind = self.index.kind(upstream)
            if kind not in ("model_output", "observation"):
                continue
            seen = upstream in graph.nodes
            self._add(graph, upstream)
            graph.edges.append(Edge(upstream, message, 1.0))
            if kind == "model_output" and not seen:
                self._output(graph, upstream, depth)


async def persist(graph: CausalGraph, backend: GraphBackend) -> int:
    """Store the graph as `ExplanationNode`s joined by `CONTRIBUTED_TO`. The in-process
    graph backend cannot set a property on a relationship, so the weights of an
    incoming edge are kept on the target node as `inputs` (JSON); Neo4j serves the
    same statements."""
    incoming: dict[str, dict[str, float]] = {}
    for e in graph.edges:
        incoming.setdefault(e.target, {})[e.source] = e.weight
    for node in graph.nodes.values():
        props = {"kind": node.kind, "label": node.label, "root": graph.root,
                 "inputs": json.dumps(incoming.get(node.id, {}), sort_keys=True)}
        await backend.run("MERGE (a:ExplanationNode {id: $id}) SET a += $props",
                          {"id": node.id, "props": {**props, "id": node.id}})
    for e in graph.edges:
        await backend.run("MATCH (a:ExplanationNode {id: $a}), (b:ExplanationNode {id: $b}) "
                          "MERGE (a)-[:CONTRIBUTED_TO]->(b)", {"a": e.source, "b": e.target})
    return len(graph.edges)
