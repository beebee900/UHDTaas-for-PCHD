"""AHDT Layer 6.1 knowledge tools and the PHKG export route (design 04, 4.7.2).

- `ahdt.data.graph_query`: questions answered by `GraphQA`
- `ahdt.data.knowledge`: allow-listed Cypher reads (`queries.READ`) and SPARQL reads over
  the person's RDF export (`sparql.READ`, ids prefixed `sparql.`)
- `ahdt.data.documents`: section search over the person's notes
- `GET /v1/persons/{hdt_id}/phkg.ttl`: FHIR RDF of the person's resources plus the PHKG
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel

from ahdt.knowledge import queries as q
from ahdt.knowledge import sparql
from ahdt.knowledge.answer import GraphQA, NoAnswer
from ahdt.knowledge.documents import PARTITION, Notes
from ahdt.knowledge.hetionet import STORE_DIR as HETIONET_STORE
from ahdt.knowledge.hetionet import Hetionet
from ahdt.knowledge.phkg import PHKG
from ahdt.knowledge.rdf import FhirRdf
from atra.backends import Backends
from atra.gateway import Role
from atra.service import Identity, Problem, ToolHandler, authenticate, verifier_of

EXPORT_TYPES = ("Observation", "Condition", "MedicationStatement", "DocumentReference")
EXPORT_ROLES = frozenset({Role.MEDICAL_OFFICER, Role.NURSE, Role.PHARMACIST,
                          Role.LAB_SCIENTIST, Role.RADIOLOGIST})
ID_PARAMS = ("id",)


def _load_guidelines() -> Any:
    from apdt.knowledge.retrieval import GuidelineIndex

    return GuidelineIndex.load()


class KnowledgeService:
    def __init__(self, backends: Backends) -> None:
        self.backends = backends
        self.phkg = PHKG(backends.graph)
        self.notes = Notes(backends.fhir, self.phkg)
        hetionet = Hetionet() if HETIONET_STORE.exists() else None
        self.qa = GraphQA(self.phkg, hetionet=hetionet, load_guidelines=_load_guidelines)
        self.sparql = sparql.SparqlStore()

    def subscribe(self) -> None:
        self.phkg.subscribe(self.backends.events)

    async def export(self, hdt_id: str) -> str:
        rdf = FhirRdf()
        for rtype in EXPORT_TYPES:
            for resource in await self.backends.fhir.search(
                    rtype, {"subject": f"Patient/{hdt_id}"}, partition=PARTITION):
                rdf.resource(resource)
        nodes, edges = await self.phkg.subgraph(hdt_id)
        rdf.phkg(nodes, edges)
        return rdf.turtle()

    async def graph_query(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        try:
            answer = await self.qa.ask(a.hdt_id, a.question, a.mode)
        except NoAnswer as exc:
            raise Problem(404, "not-found", str(exc)) from exc
        return answer.data()

    async def knowledge(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        if a.query_id.startswith("sparql."):
            name = a.query_id.removeprefix("sparql.")
            if name not in sparql.READ:
                raise Problem(400, "bad-request", f"unknown query {a.query_id}")
            self.sparql.load_person(a.hdt_id, await self.export(a.hdt_id))
            return {"rows": self.sparql.read(name, a.hdt_id)}
        if a.query_id not in q.READ:
            raise Problem(400, "bad-request", f"unknown query {a.query_id}")
        _, needed = q.READ[a.query_id]
        missing = [k for k in needed if k not in a.params]
        if missing:
            raise Problem(400, "bad-request", f"missing parameters: {', '.join(missing)}")
        for key in ID_PARAMS:
            if key in needed and f":{a.hdt_id}:" not in str(a.params[key]):
                raise Problem(403, "forbidden", "the node does not belong to this person")
        return {"rows": await self.phkg.read(a.query_id, a.hdt_id, a.params)}

    async def documents(self, args: BaseModel, ident: Identity) -> Mapping[str, Any]:
        a: Any = args
        return {"hits": await self.notes.search(a.hdt_id, a.query, types=a.types,
                                                top_k=a.top_k)}

    def handlers(self) -> dict[str, ToolHandler]:
        return {"ahdt.data.graph_query": self.graph_query, "ahdt.data.knowledge": self.knowledge,
                "ahdt.data.documents": self.documents}


def mount_export(app: FastAPI, service: KnowledgeService) -> None:
    @app.get("/v1/persons/{hdt_id}/phkg.ttl", tags=["knowledge"],
             summary="The person's health knowledge graph as FHIR RDF Turtle",
             response_class=Response)
    async def phkg_ttl(hdt_id: str, request: Request) -> Response:
        ident = await authenticate(request.headers, await verifier_of(app), hdt_id=hdt_id)
        own = ident.claims.hdt_id == hdt_id and not ident.delegated
        if not own and ident.ctx.actor_role not in EXPORT_ROLES:
            raise Problem(403, "forbidden", "this role may not export the graph")
        consent = app.state.consents.get(hdt_id)
        if not own and (consent is None or "care" not in consent.purposes):
            raise Problem(403, "forbidden", "no consent for care")
        return Response(await service.export(hdt_id), media_type="text/turtle")
