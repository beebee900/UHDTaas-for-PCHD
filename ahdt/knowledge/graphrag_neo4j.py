"""Neo4j GraphRAG vector retrieval (p1 and up; design 04, 4.4.3).

Guideline sections are `Section` nodes with a BGE-small `embedding` property and a Neo4j
vector index. `neo4j-graphrag`'s VectorCypherRetriever finds the nearest sections and the
retrieval query adds the document each belongs to. Free-text Cypher generation is not used:
questions map to the allow-listed reads of `queries.READ` (see `answer.GraphQA`).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

INDEX = "section_embedding"
DIMENSIONS = 384
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
CREATE_INDEX = (f"CREATE VECTOR INDEX {INDEX} IF NOT EXISTS FOR (s:Section) ON (s.embedding) "
                "OPTIONS {indexConfig: {`vector.dimensions`: " + str(DIMENSIONS) +
                ", `vector.similarity_function`: 'cosine'}}")
UPSERT_SECTION = ("MERGE (d:Document {id: $doc_id}) MERGE (s:Section {id: $id}) "
                  "SET s.title = $title, s.text = $text, s.embedding = $embedding "
                  "MERGE (d)-[:HAS_SECTION]->(s)")
RETRIEVAL_QUERY = ("MATCH (d:Document)-[:HAS_SECTION]->(node) "
                   "RETURN node.id AS section_id, node.title AS title, d.id AS doc_id, "
                   "node.text AS text, score")


class GuidelineVectors:
    def __init__(self, url: str, user: str, password: str) -> None:
        import neo4j
        from neo4j_graphrag.embeddings import SentenceTransformerEmbeddings

        self.driver = neo4j.GraphDatabase.driver(url, auth=(user, password))
        self.embedder = SentenceTransformerEmbeddings(model=EMBED_MODEL)

    def load(self, sections: Sequence[tuple[str, str, str, str]]) -> int:
        """(doc_id, section_id, title, text) rows; embeds and stores them."""
        self.driver.execute_query(CREATE_INDEX)
        for doc_id, section_id, title, text in sections:
            vector = self.embedder.embed_query(f"{title}\n{text}")
            self.driver.execute_query(UPSERT_SECTION, {
                "doc_id": doc_id, "id": section_id, "title": title, "text": text,
                "embedding": vector})
        return len(sections)

    def search(self, question: str, top_k: int = 5) -> list[dict[str, Any]]:
        from neo4j_graphrag.retrievers import VectorCypherRetriever

        retriever = VectorCypherRetriever(self.driver, INDEX, RETRIEVAL_QUERY,
                                          embedder=self.embedder)
        result = retriever.search(query_text=question, top_k=top_k)
        return [dict(item.metadata or {}, content=item.content) for item in result.items]

    def close(self) -> None:
        self.driver.close()
