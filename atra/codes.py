"""Code systems and code tables (design 02, section 2.8).

The tables live in `kb/terminology/<system>.csv` with the columns `code,display` and
optional extra columns. They are loaded on first use.
"""

from __future__ import annotations

import csv
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path

from atra.contracts import Code

SYSTEMS: Mapping[str, str] = {
    "loinc": "http://loinc.org",
    "snomed": "http://snomed.info/sct",
    "icd11": "http://id.who.int/icd/release/11/mms",
    "atc": "http://www.whocc.no/atc",
    "rxnorm": "http://www.nlm.nih.gov/research/umls/rxnorm",
    "uberon": "http://purl.obolibrary.org/obo/uberon.owl",
    "hpo": "http://purl.obolibrary.org/obo/hp.owl",
    "radlex": "http://radlex.org",
    "mdc": "urn:iso:std:iso:11073:10101",
    "ucum": "http://unitsofmeasure.org",
    "purpose": "http://terminology.hl7.org/CodeSystem/v3-ActReason",
    "hgnc": "http://www.genenames.org",
}

_ALIASES = {uri: name for name, uri in SYSTEMS.items()}


class UnknownCode(KeyError):
    """A code is not in the loaded table for its system."""


def system_uri(name: str) -> str:
    return SYSTEMS[name]


def system_name(uri: str) -> str:
    return _ALIASES.get(uri, uri)


def code(system: str, value: str, display: str | None = None) -> Code:
    """A `Code` with the system given by short name (`loinc`) or URI."""
    uri = SYSTEMS.get(system, system)
    return Code(system=uri, code=value, display=display)


class CodeTable:
    """One terminology table: code -> row."""

    def __init__(self, system: str, rows: Mapping[str, Mapping[str, str]]) -> None:
        self.system = system
        self.rows = dict(rows)

    @classmethod
    def load(cls, path: Path) -> CodeTable:
        with path.open(newline="", encoding="utf-8") as fh:
            rows = {r["code"]: r for r in csv.DictReader(fh)}
        return cls(path.stem, rows)

    def __contains__(self, value: object) -> bool:
        return value in self.rows

    def display(self, value: str) -> str:
        try:
            return self.rows[value]["display"]
        except KeyError:
            raise UnknownCode(f"{self.system}:{value}") from None

    def to_code(self, value: str) -> Code:
        return code(self.system, value, self.display(value))


@lru_cache(maxsize=32)
def table(system: str, kb_dir: Path | None = None) -> CodeTable:
    from atra.config import get_settings

    base = kb_dir or get_settings().kb_dir
    path = base / "terminology" / f"{system}.csv"
    if not path.exists():
        return CodeTable(system, {})
    return CodeTable.load(path)
