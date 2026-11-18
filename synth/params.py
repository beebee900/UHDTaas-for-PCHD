"""Inputs of the generators: `synth/sources.yaml`, the kb priors and CPIC allele frequencies."""

from __future__ import annotations

import json
from collections import defaultdict
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from atra.config import ROOT
from atra.kb import KnowledgeBase

HERE = Path(__file__).resolve().parent
PGX_GENES = ("CYP2B6", "CYP2C19", "CYP2C9", "CYP2D6", "G6PD")


@lru_cache(maxsize=1)
def sources() -> Mapping[str, Any]:
    data: Mapping[str, Any] = yaml.safe_load((HERE / "sources.yaml").read_text())
    return data


@lru_cache(maxsize=1)
def kb() -> KnowledgeBase:
    return KnowledgeBase(ROOT / "kb")


def prior(name: str) -> Mapping[str, Any]:
    content: Mapping[str, Any] = kb().entry(f"prior.{name}").content()
    return content


@lru_cache(maxsize=1)
def allele_frequencies() -> Mapping[str, list[tuple[str, float]]]:
    """Gene → (allele, frequency) normalised to sum to 1, from the CPIC view."""
    from apdt.knowledge.sources import load_lock, load_sources, local_copy

    srcs = load_sources()
    rows = json.loads(local_copy(srcs["cpic-frequencies"], srcs, load_lock()).read_text())
    by_gene: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        f = r.get("freq_weighted_avg")
        if r["genesymbol"] in PGX_GENES and f and f > 0:
            by_gene[r["genesymbol"]].append((str(r["name"]), float(f)))
    out = {}
    for gene, alleles in by_gene.items():
        total = sum(f for _, f in alleles)
        out[gene] = sorted(((a, f / total) for a, f in alleles), key=lambda x: (-x[1], x[0]))
    return out
