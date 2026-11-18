"""Shared ontologies: UBERON, HPO, GO and ChEBI (design 04, 4.4.1).

Each OBO release is streamed once, line by line, into an on-disk pyoxigraph store, one
named graph per ontology, with `rdfs:label` and direct `rdfs:subClassOf` links (`is_a`).
The services query the store and never hold a parsed ontology in memory.

    python -m ahdt.knowledge.ontology build      write var/ontologies/store
"""

from __future__ import annotations

import argparse
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, cast

import pyoxigraph as ox

from atra.config import ROOT

SOURCE_DIR = ROOT / "var" / "ontologies"
STORE_DIR = SOURCE_DIR / "store"
OBO = "http://purl.obolibrary.org/obo/"
RDFS = "http://www.w3.org/2000/01/rdf-schema#"
FILES: Mapping[str, str] = {"uberon": "uberon-basic.obo", "hpo": "hp.obo",
                            "go": "go-basic.obo", "chebi": "chebi_lite.obo"}
LABEL = ox.NamedNode(RDFS + "label")
SUBCLASS = ox.NamedNode(RDFS + "subClassOf")
BATCH = 50_000


def iri(curie: str) -> str:
    """`UBERON:0000945` → `http://purl.obolibrary.org/obo/UBERON_0000945`."""
    return OBO + curie.replace(":", "_", 1)


def curie(node_iri: str) -> str:
    return node_iri.removeprefix(OBO).replace("_", ":", 1)


def graph_of(name: str) -> ox.NamedNode:
    return ox.NamedNode(f"urn:atra:ontology:{name}")


def read_obo(path: Path) -> Iterator[tuple[str, str | None, list[str]]]:
    """(id, name, direct is_a parents) of every non-obsolete `[Term]`, streamed line by line."""
    term: dict[str, Any] | None = None

    def done(t: dict[str, Any] | None) -> tuple[str, str | None, list[str]] | None:
        if t and t.get("id") and not t.get("obsolete") and ":" in t["id"]:
            return t["id"], t.get("name"), t["is_a"]
        return None

    with path.open(encoding="utf-8") as fh:
        for raw in fh:
            line = raw.rstrip("\n")
            if line.startswith("["):
                if (row := done(term)) is not None:
                    yield row
                term = {"is_a": []} if line == "[Term]" else None
                continue
            if term is None or ": " not in line:
                continue
            tag, value = line.split(": ", 1)
            if tag == "id":
                term["id"] = value.strip()
            elif tag == "name":
                term["name"] = value.strip()
            elif tag == "is_a":
                term["is_a"].append(value.split("!")[0].split("{")[0].strip())
            elif tag == "is_obsolete" and value.strip() == "true":
                term["obsolete"] = True
    if (row := done(term)) is not None:
        yield row


def _quads(name: str, path: Path) -> Iterator[ox.Quad]:
    g = graph_of(name)
    for term_id, label, parents in read_obo(path):
        node = ox.NamedNode(iri(term_id))
        if label:
            yield ox.Quad(node, LABEL, ox.Literal(label), g)
        for parent in parents:
            if ":" in parent:
                yield ox.Quad(node, SUBCLASS, ox.NamedNode(iri(parent)), g)


def build(names: list[str] | None = None, *, source: Path = SOURCE_DIR,
          target: Path = STORE_DIR) -> dict[str, int]:
    """Load the named ontologies (default: every downloaded one). Returns name → quads."""
    store = ox.Store(str(target))
    counts: dict[str, int] = {}
    try:
        for name, filename in FILES.items():
            path = source / filename
            if (names and name not in names) or not path.exists():
                continue
            if store.contains_named_graph(graph_of(name)):
                store.clear_graph(graph_of(name))
            batch: list[ox.Quad] = []
            n = 0
            for quad in _quads(name, path):
                batch.append(quad)
                if len(batch) >= BATCH:
                    store.bulk_extend(batch)
                    n += len(batch)
                    batch = []
            store.bulk_extend(batch)
            counts[name] = n + len(batch)
            store.flush()
        store.optimize()
    finally:
        del store
    return counts


class Ontologies:
    """Read access to the built store."""

    def __init__(self, directory: Path = STORE_DIR) -> None:
        self.store = ox.Store.read_only(str(directory))

    def label(self, term: str) -> str | None:
        for q in self.store.quads_for_pattern(ox.NamedNode(iri(term)), LABEL, None):
            return str(cast(ox.Literal, q.object).value)
        return None

    def exists(self, term: str) -> bool:
        return self.label(term) is not None

    def ancestors(self, term: str) -> list[str]:
        """Every superclass of a term, through any number of `rdfs:subClassOf` links."""
        rows = cast(ox.QuerySolutions, self.store.query(
            f"SELECT DISTINCT ?a WHERE {{ <{iri(term)}> <{RDFS}subClassOf>+ ?a }}",
            use_default_graph_as_union=True))
        return sorted(curie(str(r["a"].value)) for r in rows)

    def is_a(self, term: str, ancestor: str) -> bool:
        return term == ancestor or ancestor in self.ancestors(term)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ahdt.knowledge.ontology")
    sub = parser.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("names", nargs="*")
    args = parser.parse_args(argv)
    if args.cmd == "build":
        for name, n in build(args.names or None).items():
            print(f"{name}: {n} quads")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
