import pytest
import yaml

from apdt.knowledge.retrieval import BM25, GuidelineIndex, answer
from apdt.knowledge.sections import TREES
from evaluation.retrieval.run import HERE, passes

needs_trees = pytest.mark.skipif(not TREES.exists() or not any(TREES.glob("*.json")),
                                 reason="section trees are built by `make kb-sources`")


def test_bm25_ranks_the_matching_document_first():
    bm = BM25(["artesunate for severe malaria", "amoxicillin for pneumonia", "malaria vaccine"])
    assert bm.scores("severe malaria treatment").argmax() == 0


@pytest.fixture(scope="module")
def index():
    return GuidelineIndex.load()


@needs_trees
async def test_scripted_questions_get_section_citations(index):
    questions = yaml.safe_load((HERE / "questions.yaml").read_text())
    assert len(questions) == 30
    passed = 0
    for item in questions:
        hits = await index.search(item["q"], "graph", 5)
        assert hits and all(h.citation.section_id and h.citation.path for h in hits)
        passed += passes(hits, item)
    assert passed >= 27


@needs_trees
def test_answer_has_contract_shape(index):
    out = answer(index.chunkless("artesunate severe malaria", 3))
    assert out["answer"] and {"doc_id", "label", "path"} <= set(out["citations"][0])
