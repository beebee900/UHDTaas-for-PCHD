"""A person's notes, reports and discharge summaries (`ahdt.data.documents`).

A note is stored as a FHIR DocumentReference with the text as a base64 attachment. On
storage it is split into medspaCy sections, which become `Document` and `Section` nodes of
the PHKG; each section `MENTIONS` the facts extracted from it. Search ranks the sections
of the person's notes with BM25, so a hit is a whole section with its path.
"""

from __future__ import annotations

import base64
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from ahdt.knowledge import queries as q
from ahdt.knowledge.extraction import NoteExtractor, apply
from ahdt.knowledge.phkg import PHKG
from atra.backends.base import FhirBackend
from atra.ids import new_record_id

type DocType = Literal["discharge_summary", "note", "report"]
PARTITION = "ahdt"
TYPE_TAG = "urn:atra:document-type"


@dataclass(frozen=True)
class Section:
    doc_id: str
    doc_type: str
    title: str
    text: str


class Notes:
    def __init__(self, fhir: FhirBackend, phkg: PHKG,
                 extractor: NoteExtractor | None = None) -> None:
        self.fhir = fhir
        self.phkg = phkg
        self.extractor = extractor or NoteExtractor(phkg.kb)

    def sections(self, doc_id: str, doc_type: str, text: str) -> list[Section]:
        doc = self.extractor.nlp(text)
        out = []
        for sec in doc._.sections:
            title = sec.category or "untitled"
            body = doc[sec.body_start:sec.body_end].text.strip()
            if body:
                out.append(Section(doc_id, doc_type, title, body))
        return out or [Section(doc_id, doc_type, "untitled", text.strip())]

    async def add(self, hdt_id: str, doc_type: DocType, text: str, *, date: datetime,
                  description: str | None = None) -> str:
        doc_id = new_record_id()
        await self.fhir.create({
            "resourceType": "DocumentReference", "id": doc_id, "status": "current",
            "meta": {"tag": [{"system": TYPE_TAG, "code": doc_type}]},
            "type": {"text": doc_type.replace("_", " ")},
            "subject": {"reference": f"Patient/{hdt_id}"}, "date": date.isoformat(),
            "description": description,
            "content": [{"attachment": {"contentType": "text/plain",
                                        "data": base64.b64encode(text.encode()).decode()}}]},
            partition=PARTITION)
        graph = self.phkg.graph
        doc_node = f"doc:{hdt_id}:{doc_id}"
        await graph.run(q.MERGE_DOCUMENT, {"id": doc_node, "props": {
            "id": doc_node, "hdt_id": hdt_id, "doc_id": doc_id, "type": doc_type}})
        for i, sec in enumerate(self.sections(doc_id, doc_type, text)):
            sec_node = f"{doc_node}:s{i}"
            await graph.run(q.MERGE_SECTION, {"id": sec_node, "props": {
                "id": sec_node, "hdt_id": hdt_id, "title": sec.title}})
            await graph.run(q.HAS_SECTION, {"a": doc_node, "b": sec_node})
            for nid in await apply(self.phkg, hdt_id, self.extractor.extract(sec.text)):
                await graph.run(q.MENTIONS, {"a": sec_node, "b": nid})
        return doc_id

    async def _notes(self, hdt_id: str, types: Sequence[str] | None) -> list[dict[str, Any]]:
        docs = await self.fhir.search("DocumentReference", {"subject": f"Patient/{hdt_id}"},
                                      partition=PARTITION)
        out = []
        for d in docs:
            dtype = next((t["code"] for t in d.get("meta", {}).get("tag", [])
                          if t.get("system") == TYPE_TAG), "note")
            if types and dtype not in types:
                continue
            data = d["content"][0]["attachment"]["data"]
            out.append({"id": d["id"], "type": dtype, "text": base64.b64decode(data).decode()})
        return out

    async def search(self, hdt_id: str, query: str, *, types: Sequence[str] | None = None,
                     top_k: int = 5) -> list[dict[str, Any]]:
        from apdt.knowledge.retrieval import BM25

        sections = [s for n in await self._notes(hdt_id, types)
                    for s in self.sections(n["id"], n["type"], n["text"])]
        if not sections:
            return []
        scores = BM25([f"{s.title} {s.text}" for s in sections]).scores(query)
        ranked = sorted(range(len(sections)), key=lambda i: -scores[i])[:top_k]
        return [{"doc_id": sections[i].doc_id,
                 "section_path": [sections[i].doc_type, sections[i].title],
                 "snippet": sections[i].text[:400], "score": round(float(scores[i]), 4)}
                for i in ranked if scores[i] > 0]
