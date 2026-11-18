"""Load the embedding and re-ranker hosts on real models and time them.

    python -m evaluation.language.hosts_check

Checks that BGE-small and BioLORD return unit-length vectors of the expected size and that the
re-ranker puts the relevant passage first on a small query set. Output:
`$ATRA/out/wp14d/eval/hosts.json`.
"""

from __future__ import annotations

import time

import numpy as np

from ahdt.models.language.embed import EmbeddingHost, RerankerHost
from evaluation.language import common

QUERY = "What are the symptoms of malaria?"
PASSAGES = [
    "Malaria causes fever, chills, headache and muscle pain.",
    "Hypertension is a long-term raised blood pressure.",
    "The immunisation card is kept at the health centre.",
]


def main() -> int:
    result: dict[str, dict[str, object]] = {}
    for key, folder in (("bge-small", "bge-small"), ("biolord", "biolord")):
        path = common.MODELS / folder
        if not path.is_dir():
            continue
        host = EmbeddingHost(path)
        t0 = time.time()
        vecs = host.encode([QUERY, *PASSAGES])
        result[key] = {"dim": host.dim, "seconds": round(time.time() - t0, 1),
                       "unit_norm": bool(np.allclose(np.linalg.norm(vecs, axis=1), 1, atol=1e-3)),
                       "nearest_passage": int(np.argmax(vecs[1:] @ vecs[0]))}
    reranker = RerankerHost(common.MODELS / "bge-reranker")
    t0 = time.time()
    ranked = reranker.rank(QUERY, PASSAGES)
    result["bge-reranker"] = {"order": [i for i, _ in ranked],
                              "seconds": round(time.time() - t0, 1)}
    common.write_json(common.OUT / "eval" / "hosts.json", result)
    common.log(str(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
