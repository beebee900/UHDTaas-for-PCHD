"""PHKG export as RDF Turtle (design 04, 4.4.1, `GET /v1/persons/{hdt_id}/phkg.ttl`).

FHIR resources follow the FHIR RDF rules (R5 form): the resource node is typed with its
resource type and marked `fhir:nodeRole fhir:treeRoot`; properties use the short element
name, so a choice element such as `valueQuantity` becomes `fhir:value` typed
`fhir:Quantity`; a primitive is a node with `fhir:v`; repeating elements are RDF lists; a
reference also carries `fhir:link` to the target; a LOINC or SNOMED CT coding is typed
with its concept IRI. PHKG nodes and edges are added under the `atra:` namespace.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

from rdflib import RDF, BNode, Graph, Literal, Namespace, URIRef
from rdflib.collection import Collection
from rdflib.namespace import XSD
from rdflib.term import Node

FHIR = Namespace("http://hl7.org/fhir/")
ATRA = Namespace("https://atra.health/phkg/")
BASE = "https://atra.health/fhir/"
CHOICE = re.compile(r"^(value|effective|onset|abatement|deceased|multipleBirth|occurrence|"
                    r"medication|asNeeded|born|performed|timing)([A-Z]\w*)$")
CONCEPT_IRI: Mapping[str, str] = {"http://loinc.org": "http://loinc.org/rdf#",
                                  "http://snomed.info/sct": "http://snomed.info/id/"}
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATETIME = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})$")


def _primitive(value: Any) -> Literal:
    if isinstance(value, bool):
        return Literal(value, datatype=XSD.boolean)
    if isinstance(value, int):
        return Literal(value, datatype=XSD.integer)
    if isinstance(value, float):
        return Literal(repr(value), datatype=XSD.decimal)
    text = str(value)
    if _DATETIME.match(text):
        return Literal(text, datatype=XSD.dateTime)
    if _DATE.match(text):
        return Literal(text, datatype=XSD.date)
    return Literal(text)


class FhirRdf:
    def __init__(self, graph: Graph | None = None) -> None:
        self.g = graph or Graph()
        self.g.bind("fhir", FHIR)
        self.g.bind("atra", ATRA)

    def _value(self, value: Any, type_name: str | None = None) -> BNode:
        node = BNode()
        if type_name:
            self.g.add((node, RDF.type, FHIR[type_name]))
        if isinstance(value, Mapping):
            self._object(node, value)
        else:
            self.g.add((node, FHIR.v, _primitive(value)))
        return node

    def _object(self, node: BNode | URIRef, obj: Mapping[str, Any]) -> None:
        if "system" in obj and "code" in obj and obj["system"] in CONCEPT_IRI:
            self.g.add((node, RDF.type, URIRef(CONCEPT_IRI[obj["system"]] + str(obj["code"]))))
        if isinstance(obj.get("reference"), str) and "/" in obj["reference"]:
            self.g.add((node, FHIR.link, URIRef(BASE + obj["reference"])))
        for key, value in obj.items():
            if key == "resourceType":
                continue
            choice = CHOICE.match(key)
            name, type_name = (choice[1], choice[2]) if choice else (key, None)
            if isinstance(value, list):
                items: list[Node] = [self._value(v, type_name) for v in value]
                head = BNode()
                Collection(self.g, head, items)
                self.g.add((node, FHIR[name], head))
            else:
                self.g.add((node, FHIR[name], self._value(value, type_name)))

    def resource(self, resource: Mapping[str, Any]) -> URIRef:
        rtype = str(resource["resourceType"])
        node = URIRef(f"{BASE}{rtype}/{resource['id']}")
        self.g.add((node, RDF.type, FHIR[rtype]))
        self.g.add((node, FHIR.nodeRole, FHIR.treeRoot))
        self._object(node, resource)
        return node

    def phkg(self, nodes: Iterable[Mapping[str, Any]],
             edges: Iterable[tuple[str, str, str]]) -> None:
        """PHKG nodes (dicts with `id` and `labels`) and (source, type, target) edges."""
        for n in nodes:
            subject = ATRA[str(n["id"])]
            for label in n.get("labels", []):
                self.g.add((subject, RDF.type, ATRA[label]))
            for key, value in n.items():
                if key not in ("id", "labels") and value is not None:
                    self.g.add((subject, ATRA[key], _primitive(value)))
        for a, rel, b in edges:
            self.g.add((ATRA[a], ATRA[rel], ATRA[b]))

    def turtle(self) -> str:
        return self.g.serialize(format="turtle")
