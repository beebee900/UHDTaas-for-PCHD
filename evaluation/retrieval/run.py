"""Score the scripted guideline questions per retrieval mode (WP21 acceptance).

    python -m evaluation.retrieval.run [--modes chunkless graph hybrid] [--k 5]

Writes `evaluation/retrieval/results.json` and prints the pass rate per mode.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import yaml

from apdt.knowledge.retrieval import Embedder, GuidelineIndex, Hit

HERE = Path(__file__).resolve().parent


def passes(hits: list[Hit], item: dict[str, Any]) -> bool:
    wanted = [(item["source"], item["section"]), *map(tuple, item.get("accept", []))]
    return any(h.citation.source == src and sec.lower() in h.citation.title.lower()
               for h in hits for src, sec in wanted)


async def run(modes: list[str], k: int) -> dict[str, Any]:
    questions = yaml.safe_load((HERE / "questions.yaml").read_text())
    dense = {"vector", "hybrid"} & set(modes)
    vectors = None
    if dense:
        from atra.backends.memory import QdrantVectors

        vectors = QdrantVectors()
    ix = GuidelineIndex.load(vectors=vectors, embedder=Embedder() if dense else None)
    if dense:
        await ix.build_vectors()
    report: dict[str, Any] = {"k": k, "modes": {}}
    for mode in modes:
        rows = []
        for item in questions:
            hits = await ix.search(item["q"], mode, k)  # type: ignore[arg-type]
            rows.append({"q": item["q"], "pass": passes(hits, item),
                         "citations": [h.as_dict()["citation"] for h in hits]})
        report["modes"][mode] = {"pass_rate": sum(r["pass"] for r in rows) / len(rows),
                                 "rows": rows}
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", nargs="+", default=["chunkless", "graph"])
    ap.add_argument("--k", type=int, default=5)
    args = ap.parse_args()
    report = asyncio.run(run(args.modes, args.k))
    (HERE / "results.json").write_text(json.dumps(report, indent=2))
    for mode, r in report["modes"].items():
        failed = [row["q"] for row in r["rows"] if not row["pass"]]
        print(f"{mode}: {r['pass_rate']:.0%} ({len(r['rows']) - len(failed)}/{len(r['rows'])})")
        for q in failed:
            print(f"  miss: {q}")


if __name__ == "__main__":
    main()
