"""Embedding and re-ranking model hosts (design 04, 4.5.3; design 01, 1.3).

`EmbeddingHost` serves BGE-small-en-v1.5 (general) and BioLORD-2023 (biomedical) through
sentence-transformers; `RerankerHost` serves `BAAI/bge-reranker-base` as a cross-encoder. Both
load on first use from a local folder or a model id, on CPU. The re-ranker (1.1 GB) and BioLORD
run on the VM; on the laptop the hosts take the same folder layout under `var/models/language/`.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from atra.config import ROOT

MODELS_DIR = ROOT / "var" / "models" / "language"
BGE_SMALL = "BAAI/bge-small-en-v1.5"
BIOLORD = "FremyCompany/BioLORD-2023"
RERANKER = "BAAI/bge-reranker-base"


class EmbeddingHost:
    def __init__(self, model: str | Path = BGE_SMALL, *, threads: int = 2) -> None:
        self.model_name, self.threads = str(model), threads
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._model is None:
            import torch
            from sentence_transformers import SentenceTransformer

            torch.set_num_threads(self.threads)
            self._model = SentenceTransformer(self.model_name, device="cpu")
        return self._model

    @property
    def dim(self) -> int:
        with self._lock:
            return int(self._load().get_sentence_embedding_dimension())

    def encode(self, texts: Sequence[str], *, batch_size: int = 32) -> NDArray[np.float32]:
        """L2-normalised embeddings, one row per text."""
        with self._lock:
            out = self._load().encode(list(texts), batch_size=batch_size,
                                      normalize_embeddings=True)
        return np.asarray(out, dtype=np.float32)


class RerankerHost:
    def __init__(self, model: str | Path = RERANKER, *, threads: int = 2,
                 max_length: int = 512) -> None:
        self.model_name, self.threads, self.max_length = str(model), threads, max_length
        self._model: Any = None
        self._lock = threading.Lock()

    def _load(self) -> Any:
        if self._model is None:
            import torch
            from sentence_transformers import CrossEncoder

            torch.set_num_threads(self.threads)
            self._model = CrossEncoder(self.model_name, device="cpu", max_length=self.max_length)
        return self._model

    def scores(self, query: str, passages: Sequence[str]) -> list[float]:
        with self._lock:
            raw = self._load().predict([(query, p) for p in passages])
        return [float(s) for s in raw]

    def rank(self, query: str, passages: Sequence[str], top_k: int | None = None
             ) -> list[tuple[int, float]]:
        """(index, score) pairs, best first."""
        scored = sorted(enumerate(self.scores(query, passages)), key=lambda t: -t[1])
        return scored[:top_k] if top_k else scored
