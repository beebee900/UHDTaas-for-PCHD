"""Hetionet v1.0 as the domain knowledge graph (design 04, 4.4.2).

Only the node kinds the twins use are kept: Disease, Gene, Compound, Anatomy, Symptom,
Side Effect and Pharmacologic Class, with every edge between two kept nodes. The release
JSON (bzip2) is streamed record by record into an on-disk pyoxigraph store; it is never
loaded whole. kb conditions are linked to Hetionet diseases with the same name.

    python -m ahdt.knowledge.hetionet build
"""

from __future__ import annotations

import argparse
import bz2
import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import pyoxigraph as ox

from atra.config import ROOT
from atra.kb import KnowledgeBase

SOURCE = ROOT / "var" / "hetionet" / "hetionet-v1.0.json.bz2"
STORE_DIR = ROOT / "var" / "hetionet" / "store"
HET = "https://het.io/"
RDFS_LABEL = ox.NamedNode("http://www.w3.org/2000/01/rdf-schema#label")
RDF_TYPE = ox.NamedNode("http://www.w3.org/1999/02/22-rdf-syntax-ns#type")
KINDS = frozenset({"Disease", "Gene", "Compound", "Anatomy", "Symptom", "Side Effect",
                   "Pharmacologic Class"})
GRAPH = ox.NamedNode("urn:atra:hetionet")
KB_LINK = ox.NamedNode(HET + "kbCondition")
BATCH = 50_000


def _slug(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")


def node_iri(kind: str, identifier: Any) -> ox.NamedNode:
    return ox.NamedNode(f"{HET}{_slug(kind)}/{_slug(str(identifier))}")


def records(path: Path = SOURCE) -> Iterator[tuple[str, dict[str, Any]]]:
    """("nodes" | "edges", record) for every element of the two top-level arrays.

    The release file is indented by two spaces per level: an array element opens with a
    line that is exactly four spaces and `{`, and closes at the matching four-space `}`.
    """
    section: str | None = None
    buf: list[str] = []
    with bz2.open(path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if line.startswith('  "nodes": ['):
                section = "nodes"
                continue
            if line.startswith('  "edges": ['):
                section = "edges"
                continue
            if section is None:
                continue
            if line.startswith("  ]"):
                section = None
                continue
            if line.rstrip() == "    {":
                buf = [line]
            elif buf:
                buf.append(line)
                if line.rstrip() in ("    }", "    },"):
                    yield section, json.loads("".join(buf).rstrip().rstrip(","))
                    buf = []


def build(path: Path = SOURCE, target: Path = STORE_DIR) -> dict[str, int]:
    store = ox.Store(str(target))
    if store.contains_named_graph(GRAPH):
        store.clear_graph(GRAPH)
    kept: set[tuple[str, str]] = set()
    names: dict[str, ox.NamedNode] = {}
    counts = {"nodes": 0, "edges": 0}
    batch: list[ox.Quad] = []

    def flush() -> None:
        store.bulk_extend(batch)
        batch.clear()

    for section, rec in records(path):
        if section == "nodes":
            if rec["kind"] not in KINDS:
                continue
            node = node_iri(rec["kind"], rec["identifier"])
            kept.add((rec["kind"], str(rec["identifier"])))
            batch.append(ox.Quad(node, RDF_TYPE, ox.NamedNode(HET + _slug(rec["kind"])), GRAPH))
            batch.append(ox.Quad(node, RDFS_LABEL, ox.Literal(str(rec["name"])), GRAPH))
            if rec["kind"] == "Disease":
                names[str(rec["name"]).lower()] = node
            counts["nodes"] += 1
        else:
            (sk, sid), (tk, tid) = rec["source_id"], rec["target_id"]
            if (sk, str(sid)) not in kept or (tk, str(tid)) not in kept:
                continue
            batch.append(ox.Quad(node_iri(sk, sid), ox.NamedNode(HET + _slug(rec["kind"])),
                                 node_iri(tk, tid), GRAPH))
            counts["edges"] += 1
        if len(batch) >= BATCH:
            flush()
    flush()
    counts["kb_links"] = _link_kb(store, names)
    store.flush()
    store.optimize()
    return counts


def _link_kb(store: ox.Store, diseases: Mapping[str, ox.NamedNode]) -> int:
    kb = KnowledgeBase(ROOT / "kb")
    links = []
    for eid in kb.ids():
        if eid.startswith("cond."):
            name = str(kb.entry(eid).content().get("name", "")).lower()
            if name in diseases:
                links.append(ox.Quad(diseases[name], KB_LINK, ox.Literal(eid), GRAPH))
    store.bulk_extend(links)
    return len(links)


class Hetionet:
    def __init__(self, directory: Path = STORE_DIR) -> None:
        self.store = ox.Store.read_only(str(directory))

    def query(self, sparql: str) -> list[dict[str, str | None]]:
        solutions = cast(ox.QuerySolutions,
                         self.store.query(sparql, use_default_graph_as_union=True))
        names = [v.value for v in solutions.variables]
        return [{n: (row[n].value if row[n] is not None else None) for n in names}
                for row in solutions]

    def disease(self, kb_condition: str) -> str | None:
        rows = self.query(f'SELECT ?d WHERE {{ ?d <{KB_LINK.value}> "{kb_condition}" }}')
        return rows[0]["d"] if rows else None

    def neighbours(self, node: str, edge: str, kind: str) -> list[str]:
        """Labels of nodes of `kind` linked to `node` by `edge`, in either direction."""
        e, k = HET + _slug(edge), HET + _slug(kind)
        rows = self.query(
            "SELECT DISTINCT ?label WHERE { "
            f"{{ <{node}> <{e}> ?n }} UNION {{ ?n <{e}> <{node}> }} "
            f"?n a <{k}> ; <{RDFS_LABEL.value}> ?label }} ORDER BY ?label")
        return [str(r["label"]) for r in rows]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ahdt.knowledge.hetionet")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        print(build())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
