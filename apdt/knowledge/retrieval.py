"""Guideline retrieval with section-level citations (design 05, 5.4.2).

Modes (contract `ahdt.data.graph_query` / APDT 6.1):

- `chunkless`: BM25 over whole sections of the section trees (titles weighted), so a hit
  is a section with its breadcrumb path, never an arbitrary chunk
- `vector`: dense BGE-small passages (~200 words, inside one section) in the `guidelines`
  collection of the vector backend
- `hybrid`: reciprocal-rank fusion of passage BM25 and dense passages
- `graph`: local search over the kb graph: kb entries named in the question lead to the
  sections their provenance cites; fused with the chunkless ranking

Every hit carries `{source, section_id, number, title, path, page}`. The Microsoft GraphRAG
community index (design 01) is a separate LLM-built index and is not part of this module.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from scipy import sparse

from apdt.knowledge.sections import TREES, SectionTree, load_tree
from atra.backends.base import VectorBackend
from atra.config import ROOT
from atra.kb import KnowledgeBase

type Mode = Literal["chunkless", "vector", "hybrid", "graph"]
INDEX_DIR = TREES.parent / "kb_index"
COLLECTION = "guidelines"
EMBED_MODEL = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence for searching relevant passages: "
PASSAGE_WORDS = 200
TITLE_WEIGHT = 3
RRF_K = 60
# Share of a kb entry's name tokens that must appear in the question for graph mode.
MATCH_SHARE = 2 / 3
_TOKEN = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")
_STOP = frozenset((
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "how", "in",
    "is", "it", "of", "on", "or", "that", "the", "this", "to", "was", "were", "what", "when",
    "which", "who", "with", "should", "does", "do", "can",
))


def tokens(text: str) -> list[str]:
    return [t for t in _TOKEN.findall(text.lower()) if t not in _STOP]


@dataclass(frozen=True)
class Citation:
    source: str
    section_id: str
    number: str | None
    title: str
    path: str
    page: int


@dataclass
class Hit:
    citation: Citation
    score: float
    text: str
    mode: str
    via: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {**asdict(self), "citation": asdict(self.citation)}


@dataclass(frozen=True)
class Unit:
    """A searchable unit: a whole section or a passage inside one section."""

    uid: str
    citation: Citation
    text: str


def _breadcrumb(by_id: Mapping[str, Any], section_id: str) -> str:
    parts: list[str] = []
    sid: str | None = section_id
    while sid is not None and sid in by_id:
        parts.append(by_id[sid].title)
        sid = by_id[sid].parent
    return " > ".join(reversed(parts))


def units(trees: Iterable[SectionTree], *, passages: bool) -> Iterator[Unit]:
    for tree in trees:
        by_id = {s.id: s for s in tree.sections}
        for s in tree.sections:
            path = _breadcrumb(by_id, s.id)
            if not passages:
                text = s.text
                if len(text.split()) >= 5:
                    yield Unit(f"{tree.source}#{s.id}",
                               Citation(tree.source, s.id, s.number, s.title, path, s.page_start),
                               text)
                continue
            buf: list[str] = []
            page = s.page_start
            n = 0
            for line in [*s.lines, None]:
                words = sum(len(b.split()) for b in buf)
                if line is None or (words >= PASSAGE_WORDS and buf):
                    if words >= 5:
                        yield Unit(f"{tree.source}#{s.id}#{n}",
                                   Citation(tree.source, s.id, s.number, s.title, path, page),
                                   f"{s.title}. " + " ".join(buf))
                        n += 1
                    buf = []
                    if line is None:
                        break
                if not buf:
                    page = line.page
                buf.append(line.text)


class BM25:
    """Okapi BM25 over a sparse term matrix (k1 = 1.5, b = 0.75)."""

    def __init__(self, docs: Sequence[str], *, k1: float = 1.5, b: float = 0.75) -> None:
        vocab: dict[str, int] = {}
        rows, cols, vals = [], [], []
        lengths = np.zeros(len(docs))
        for i, doc in enumerate(docs):
            counts: dict[int, int] = {}
            toks = tokens(doc)
            lengths[i] = len(toks)
            for t in toks:
                j = vocab.setdefault(t, len(vocab))
                counts[j] = counts.get(j, 0) + 1
            rows += [i] * len(counts)
            cols += list(counts)
            vals += list(counts.values())
        tf = sparse.csr_matrix((vals, (rows, cols)), shape=(len(docs), len(vocab)), dtype=float)
        df = np.bincount(tf.indices, minlength=len(vocab))
        self.idf = np.log(1 + (len(docs) - df + 0.5) / (df + 0.5))
        norm = k1 * (1 - b + b * lengths / max(lengths.mean(), 1.0))
        tf = tf.tocoo()
        weights = tf.data * (k1 + 1) / (tf.data + norm[tf.row])
        self.matrix = sparse.csc_matrix((weights, (tf.row, tf.col)), shape=tf.shape)
        self.vocab = vocab

    def scores(self, query: str) -> NDArray[np.float64]:
        cols = [self.vocab[t] for t in set(tokens(query)) if t in self.vocab]
        if not cols:
            return np.zeros(self.matrix.shape[0])
        out: NDArray[np.float64] = np.asarray(self.matrix[:, cols] @ self.idf[cols]).ravel()
        return out


class Embedder:
    """BGE-small on CPU (design 01). Loaded on first use."""

    def __init__(self, model: str = EMBED_MODEL) -> None:
        self.model_name = model
        self._model: Any = None

    @property
    def model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer

            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    @property
    def dim(self) -> int:
        return int(self.model.get_sentence_embedding_dimension())

    def passages(self, texts: Sequence[str], *, batch_size: int = 32) -> NDArray[np.float32]:
        out: NDArray[np.float32] = np.asarray(self.model.encode(
            list(texts), batch_size=batch_size, normalize_embeddings=True), dtype=np.float32)
        return out

    def query(self, text: str) -> NDArray[np.float32]:
        vec: NDArray[np.float32] = self.passages([QUERY_PREFIX + text])[0]
        return vec


class GuidelineIndex:
    def __init__(self, trees: Sequence[SectionTree], *, kb: KnowledgeBase | None = None,
                 vectors: VectorBackend | None = None, embedder: Embedder | None = None) -> None:
        self.trees = {t.source: t for t in trees}
        self.sections = list(units(trees, passages=False))
        self.passages = list(units(trees, passages=True))
        self._section_pos = {u.uid: i for i, u in enumerate(self.sections)}
        self.section_bm25 = BM25([(u.citation.title + " ") * TITLE_WEIGHT + u.text
                                  for u in self.sections])
        self.passage_bm25 = BM25([u.text for u in self.passages])
        self.kb = kb or KnowledgeBase(ROOT / "kb")
        self.vectors = vectors
        self.embedder = embedder
        self._kb_terms = self._kb_lexicon()
        self._by_key: dict[tuple[str, str, Any], list[Unit]] = {}
        for u in self.sections:
            c = u.citation
            for key in ((c.source, "title", c.title), (c.source, "page", c.page),
                        *([(c.source, "number", c.number)] if c.number else [])):
                self._by_key.setdefault(key, []).append(u)

    @classmethod
    def load(cls, source_ids: Iterable[str] | None = None, **kw: Any) -> GuidelineIndex:
        ids = list(source_ids) if source_ids is not None else sorted(
            p.stem for p in TREES.glob("*.json"))
        return cls([load_tree(i) for i in ids], **kw)

    # -- dense index ---------------------------------------------------------------

    def _cache_paths(self) -> tuple[Path, Path]:
        sig = "-".join(sorted(f"{t.source}:{t.sha256[:8]}" for t in self.trees.values()))
        key = _digest(sig)
        return INDEX_DIR / f"{key}.npy", INDEX_DIR / f"{key}.ids.json"

    def embeddings(self, *, batch_size: int = 32) -> NDArray[np.float32]:
        """Passage embeddings, cached under var/kb_index by the trees' hashes."""
        if self.embedder is None:
            raise RuntimeError("no embedder configured")
        npy, ids = self._cache_paths()
        if npy.exists() and ids.exists() \
                and json.loads(ids.read_text()) == [u.uid for u in self.passages]:
            cached: NDArray[np.float32] = np.load(npy)
            return cached
        emb = self.embedder.passages([u.text for u in self.passages], batch_size=batch_size)
        INDEX_DIR.mkdir(parents=True, exist_ok=True)
        np.save(npy, emb)
        ids.write_text(json.dumps([u.uid for u in self.passages]))
        return emb

    async def build_vectors(self, *, batch: int = 512) -> int:
        if self.vectors is None:
            raise RuntimeError("no vector backend configured")
        emb = self.embeddings()
        await self.vectors.ensure_collection(COLLECTION, emb.shape[1])
        for start in range(0, len(self.passages), batch):
            chunk = self.passages[start:start + batch]
            await self.vectors.upsert(COLLECTION, [
                (u.uid, emb[start + i].tolist(), {"text": u.text, **asdict(u.citation)})
                for i, u in enumerate(chunk)])
        return len(self.passages)

    # -- search --------------------------------------------------------------------

    def _top(self, scores: NDArray[np.float64], pool: Sequence[Unit], k: int,
             mode: str) -> list[Hit]:
        order = np.argsort(-scores)[:k]
        return [Hit(pool[i].citation, float(scores[i]), pool[i].text, mode)
                for i in order if scores[i] > 0]

    def chunkless(self, question: str, k: int = 5) -> list[Hit]:
        return self._top(self.section_bm25.scores(question), self.sections, k, "chunkless")

    async def vector(self, question: str, k: int = 5) -> list[Hit]:
        if self.vectors is None or self.embedder is None:
            raise RuntimeError("vector mode needs a vector backend and an embedder")
        hits = await self.vectors.search(COLLECTION, self.embedder.query(question).tolist(),
                                         top_k=k)
        out = []
        for h in hits:
            p = dict(h.payload)
            text = p.pop("text")
            out.append(Hit(Citation(**p), h.score, text, "vector"))
        return out

    async def hybrid(self, question: str, k: int = 5, *, depth: int = 50) -> list[Hit]:
        lexical = self._top(self.passage_bm25.scores(question), self.passages, depth, "bm25")
        dense = await self.vector(question, depth)
        fused: dict[tuple[str, str, int], tuple[float, Hit]] = {}
        for ranked in (lexical, dense):
            for rank, hit in enumerate(ranked):
                key = (hit.citation.source, hit.citation.section_id, hit.citation.page)
                prev = fused.get(key, (0.0, hit))[0]
                fused[key] = (prev + 1 / (RRF_K + rank + 1), hit)
        best = sorted(fused.values(), key=lambda x: -x[0])[:k]
        return [Hit(h.citation, s, h.text, "hybrid") for s, h in best]

    def _kb_lexicon(self) -> dict[str, set[str]]:
        """kb entry id → its name tokens, for entries whose names identify a concept."""
        out: dict[str, set[str]] = {}
        for eid in self.kb.ids():
            if eid.startswith(("cond.", "find.", "dose.", "test.")):
                content = self.kb.entry(eid).content()
                name = str(content.get("name") or content.get("drug") or "")
                toks = set(tokens(name.split("(")[0]))
                if toks:
                    out[eid] = toks
        return out

    def _related(self, eid: str) -> set[str]:
        """kb entries one hop from `eid`: a condition's treatments, regimens, severity rule,
        tests and associations."""
        out = {eid}
        if eid.startswith("cond."):
            sev = self.kb.entry(eid).content().get("severity_rule")
            if sev:
                out.add(sev)
            for other in self.kb.ids():
                content = self.kb.entry(other).content()
                if content.get("condition") == eid or any(
                        t.get("condition") == eid for t in content.get("targets", [])):
                    out.add(other)
                    reg = content.get("regimen")
                    out.update(reg if isinstance(reg, list) else [reg] if reg else [])
        return out

    def graph(self, question: str, k: int = 5, *, depth: int = 50) -> list[Hit]:
        """Sections cited by kb entries named in the question, fused with chunkless ranking."""
        q = set(tokens(question))
        matched = [eid for eid, toks in self._kb_terms.items()
                   if len(toks & q) / len(toks) >= MATCH_SHARE]
        cited: dict[str, list[str]] = {}
        for eid in matched:
            for rel in self._related(eid):
                if rel not in self.kb:
                    continue
                for cite in self.kb.entry(rel).provenance.citations():
                    if cite.source not in self.trees:
                        continue
                    for unit in self._sections_for(cite.source, cite.section, cite.page):
                        cited.setdefault(unit.uid, []).append(rel)
        scores = self.section_bm25.scores(question)
        graph_rank = sorted(cited, key=lambda uid: -scores[self._section_pos[uid]])
        lexical_rank = [self.sections[i].uid for i in np.argsort(-scores)[:depth] if scores[i] > 0]
        fused: dict[str, float] = {}
        for ranked in (graph_rank, lexical_rank):
            for rank, uid in enumerate(ranked):
                fused[uid] = fused.get(uid, 0.0) + 1 / (RRF_K + rank + 1)
        best = sorted(fused, key=lambda uid: -fused[uid])[:k]
        return [Hit(self.sections[self._section_pos[uid]].citation, fused[uid],
                    self.sections[self._section_pos[uid]].text, "graph",
                    sorted(set(cited.get(uid, []))))
                for uid in best]

    def _sections_for(self, source: str, section: str | None, page: int | None) -> list[Unit]:
        if section:
            number = section.split(" ", 1)[0]
            return (self._by_key.get((source, "title", section))
                    or self._by_key.get((source, "number", number), []))
        return self._by_key.get((source, "page", page), []) if page is not None else []

    async def search(self, question: str, mode: Mode = "chunkless", k: int = 5) -> list[Hit]:
        if mode == "chunkless":
            return self.chunkless(question, k)
        if mode == "graph":
            return self.graph(question, k)
        if mode == "vector":
            return await self.vector(question, k)
        return await self.hybrid(question, k)


def _digest(text: str) -> str:
    import hashlib

    return hashlib.sha256(text.encode()).hexdigest()[:16]


def citations(hits: Iterable[Hit]) -> list[dict[str, Any]]:
    """Contract shape of `ahdt.data.graph_query` citations."""
    return [{"doc_id": h.citation.source, "label": f"{h.citation.title} (p. {h.citation.page})",
             "path": h.citation.path} for h in hits]


def answer(hits: Sequence[Hit], max_chars: int = 600) -> Mapping[str, Any]:
    if not hits:
        return {"answer": "", "citations": []}
    return {"answer": hits[0].text[:max_chars], "citations": citations(hits)}
