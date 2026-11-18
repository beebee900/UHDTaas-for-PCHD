"""`kb/code_to_twin.csv`: code → owning AHDT twin (design 05, 5.9; design 04, PHKG `OWNED_BY`).

The table is generated, never edited by hand:

- LOINC codes of twin fields → the twin that defines the field
- SNOMED CT and ICD-11 codes of conditions → the condition's `twin`
- LOINC codes of tests → the twin of the field with that code, else of the first target condition
- ATC codes of regimens → the twin of the ATC anatomical main group (ATC is anatomical by design)
"""

from __future__ import annotations

import csv
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from ahdt.registry import load_registry
from atra.config import ROOT
from atra.kb import KnowledgeBase

# ATC anatomical main group (or a more specific prefix) → system twin. Longest prefix wins.
ATC_TWIN: Mapping[str, str] = {
    "A": "digestive",
    "A10": "endocrine",
    "B": "haematological",
    "C": "cardiovascular",
    "D": "integumentary",
    "G": "reproductive",
    "G04": "renal_urinary",
    "H": "endocrine",
    "J": "immune_lymphatic",
    "L": "immune_lymphatic",
    "M": "musculoskeletal",
    "N": "nervous",
    "N05": "behavioural_cognitive",
    "N06": "behavioural_cognitive",
    "P": "immune_lymphatic",
    "R": "respiratory",
    "S": "sensory",
    "V": "whole_body",
}

HEADER = ("system", "code", "twin", "origin")


def atc_twin(code: str) -> str:
    prefix = max((p for p in ATC_TWIN if code.startswith(p)), key=len)
    return ATC_TWIN[prefix]


def _atc_codes(obj: Any) -> Iterator[str]:
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if k == "atc" and isinstance(v, str):
                yield v
            else:
                yield from _atc_codes(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _atc_codes(v)


def rows(kb: KnowledgeBase) -> list[tuple[str, str, str, str]]:
    out: dict[tuple[str, str], tuple[str, str, str, str]] = {}

    def add(system: str, code: str, twin: str, origin: str) -> None:
        out.setdefault((system, code), (system, code, twin, origin))

    field_twin: dict[str, str] = {}
    for kind, definition in load_registry().twins.items():
        for f in definition.fields:
            if f.loinc:
                field_twin[f.loinc] = kind.value
                add("loinc", f.loinc, kind.value, f"field:{f.name}")
    for eid in kb.ids():
        content = kb.entry(eid).content()
        if eid.startswith("cond."):
            for system in ("snomed", "icd11"):
                if content.get(system):
                    add(system, str(content[system]), content["twin"], eid)
        elif eid.startswith("test.") and content.get("loinc"):
            loinc = str(content["loinc"])
            twin = field_twin.get(loinc)
            if twin is None and content.get("targets"):
                twin = kb.entry(content["targets"][0]["condition"]).content()["twin"]
            if twin is not None:
                add("loinc", loinc, twin, eid)
        for code in _atc_codes(content):
            add("atc", code, atc_twin(code), eid)
    return sorted(out.values())


def write(path: Path = ROOT / "kb" / "code_to_twin.csv", kb_dir: Path = ROOT / "kb") -> int:
    table = rows(KnowledgeBase(kb_dir))
    with path.open("w", newline="") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(HEADER)
        w.writerows(table)
    return len(table)


def read(path: Path = ROOT / "kb" / "code_to_twin.csv") -> dict[tuple[str, str], str]:
    with path.open(newline="") as fh:
        return {(r["system"], r["code"]): r["twin"] for r in csv.DictReader(fh)}
