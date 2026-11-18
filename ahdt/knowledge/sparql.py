"""SPARQL over the RDF export (design 04, 4.7.2: pyoxigraph store served by the 6.1 data
service). Each person's export is one named graph; queries run inside that graph only,
from the allow-list below."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, cast

import pyoxigraph as ox

PREFIXES = ("PREFIX fhir: <http://hl7.org/fhir/> PREFIX atra: <https://atra.health/phkg/> "
            "PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> ")

READ: Mapping[str, str] = {
    "observations": PREFIXES + (
        "SELECT ?resource ?code ?value WHERE { GRAPH $g { ?resource a fhir:Observation ; "
        "fhir:code/fhir:coding/rdf:rest*/rdf:first/fhir:code/fhir:v ?code . "
        "OPTIONAL { ?resource fhir:value/fhir:value/fhir:v ?value } } } ORDER BY ?code"),
    "conditions": PREFIXES + (
        "SELECT ?node ?name WHERE { GRAPH $g { ?node a atra:Condition ; atra:name ?name } } "
        "ORDER BY ?name"),
    "owners": PREFIXES + (
        "SELECT ?node ?system WHERE { GRAPH $g { ?node atra:OWNED_BY ?system } } "
        "ORDER BY ?node"),
}


def person_graph(hdt_id: str) -> ox.NamedNode:
    return ox.NamedNode(f"urn:atra:person:{hdt_id}")


class SparqlStore:
    def __init__(self, path: Path | None = None) -> None:
        self.store = ox.Store(str(path)) if path else ox.Store()

    def load_person(self, hdt_id: str, turtle: str) -> None:
        g = person_graph(hdt_id)
        if self.store.contains_named_graph(g):
            self.store.clear_graph(g)
        self.store.load(turtle.encode("utf-8"), ox.RdfFormat.TURTLE, to_graph=g)

    def read(self, query_id: str, hdt_id: str) -> list[dict[str, Any]]:
        sparql = READ[query_id].replace("$g", f"<{person_graph(hdt_id).value}>")
        solutions = cast(ox.QuerySolutions, self.store.query(sparql))
        names = [v.value for v in solutions.variables]
        return [{n: (row[n].value if row[n] is not None else None) for n in names}
                for row in solutions]
