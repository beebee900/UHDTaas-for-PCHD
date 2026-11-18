"""Score the scripted `ahdt.data.graph_query` questions (WP13 acceptance).

    python -m evaluation.graph_query.run

Seeds the persona facts (`synth/personas/facts.yaml`) into an in-process PHKG, asks every
question, and checks the expected text and that every citation resolves. Writes
`results.json`.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import yaml

from ahdt.knowledge import queries as q
from ahdt.knowledge.answer import Answer, GraphQA, NoAnswer, seed
from ahdt.knowledge.hetionet import STORE_DIR as HETIONET_STORE
from ahdt.knowledge.hetionet import Hetionet
from ahdt.knowledge.phkg import PHKG
from atra.backends.graph import NetworkXGraph
from atra.personas import BY_KEY
from synth.personas import facts

HERE = Path(__file__).resolve().parent


async def build(graph: Any = None) -> tuple[GraphQA, PHKG]:
    phkg = PHKG(graph or NetworkXGraph())
    for key, persona_facts in facts().items():
        await seed(phkg, BY_KEY[key].hdt_id, persona_facts)
    hetionet = Hetionet() if HETIONET_STORE.exists() else None
    from apdt.knowledge.retrieval import GuidelineIndex

    return GraphQA(phkg, hetionet=hetionet, guidelines=GuidelineIndex.load()), phkg


async def resolves(cite: dict[str, Any], qa: GraphQA) -> bool:
    if cite.get("node_id"):
        return bool(await qa.phkg.graph.run(q.NODE_BY_ID, {"id": cite["node_id"]}))
    doc = str(cite.get("doc_id", ""))
    if doc.startswith("kb:"):
        return doc[3:] in qa.phkg.kb
    if doc.startswith("https://het.io/") and qa.hetionet is not None:
        return bool(qa.hetionet.query(f"SELECT ?p WHERE {{ <{doc}> ?p ?o }} LIMIT 1"))
    if "#" in doc and qa.guidelines is not None:
        from apdt.knowledge.sections import load_tree

        source, section = doc.split("#", 1)
        try:
            load_tree(source).by_id(section)
        except (KeyError, FileNotFoundError):
            return False
        return True
    return False


async def score(qa: GraphQA, item: dict[str, Any]) -> dict[str, Any]:
    hdt_id = BY_KEY[item["persona"]].hdt_id
    try:
        ans: Answer | None = await qa.ask(hdt_id, item["q"], item.get("mode", "hybrid"))
    except NoAnswer as exc:
        return {**item, "pass": False, "answer": f"no answer: {exc}"}
    text = ans.answer.lower()
    missing = [e for e in item["expect"] if e.lower() not in text]
    if item.get("cite") and not any(item["cite"].lower() in str(c.get("label", "")).lower()
                                    for c in ans.citations):
        missing.append(f"citation {item['cite']}")
    unresolved = [c for c in ans.citations if not await resolves(c, qa)]
    ok = not missing and bool(ans.citations) and not unresolved
    return {**item, "pass": ok, "answer": ans.answer, "missing": missing,
            "citations": ans.citations, "unresolved": unresolved}


async def run() -> dict[str, Any]:
    qa, _ = await build()
    questions = yaml.safe_load((HERE / "questions.yaml").read_text())
    results = [await score(qa, item) for item in questions]
    summary = {"passed": sum(r["pass"] for r in results), "total": len(results),
               "results": results}
    (HERE / "results.json").write_text(json.dumps(summary, indent=1, default=str))
    return summary


def main() -> int:
    summary = asyncio.run(run())
    for r in summary["results"]:
        print(("PASS " if r["pass"] else "FAIL ") + r["q"] + " -> " + r["answer"][:110])
    print(f"{summary['passed']}/{summary['total']}")
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
