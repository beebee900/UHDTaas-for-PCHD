"""Curated code tables of the kb (design 06, 6.3.1 `terminology/*.csv`).

Every code written in a kb entry is looked up in its code system before it is accepted, and its
official display is stored in `kb/terminology/<system>.csv`. A code that the code system does not
know is an error. Full releases need licences (design 01, P10), so lookups use public services:

- SNOMED CT, ICD-11 MMS and LOINC: the HL7 FHIR terminology server tx.fhir.org
- ATC: the WHO Collaborating Centre ATC/DDD index
- RxNorm: the NLM RxNav API
- HPO and UBERON: the OBO releases in var/ontologies

Answers are cached in var/terminology_cache.json, so a verify run only queries new codes.
"""

from __future__ import annotations

import csv
import html
import json
import re
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

import httpx

from atra.codes import SYSTEMS
from atra.config import ROOT
from atra.kb import KnowledgeBase

TERMINOLOGY = ROOT / "kb" / "terminology"
CACHE = ROOT / "var" / "terminology_cache.json"
ONTOLOGIES = ROOT / "var" / "ontologies"
TX = "https://tx.fhir.org/r4"
CODE_KEYS = ("snomed", "icd11", "loinc", "atc", "rxnorm", "hpo", "uberon")
_FHIR = {"Accept": "application/fhir+json"}


class Terminology:
    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or httpx.Client(timeout=60, follow_redirects=True)
        self.cache: dict[str, Any] = (json.loads(CACHE.read_text(encoding="utf-8"))
                                      if CACHE.exists() else {})
        self._obo: dict[str, dict[str, str]] = {}

    def save(self) -> None:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps(self.cache, indent=0, sort_keys=True), encoding="utf-8")

    # Lookup -------------------------------------------------------------------------------
    def lookup(self, system: str, code: str) -> dict[str, str] | None:
        """{display, version, via} of a code, or None when the code system does not know it."""
        key = f"{system}|{code}"
        if self.cache.get(key) is None:
            self.cache[key] = self._lookup(system, code)
        found: dict[str, str] | None = self.cache[key]
        return found

    def _lookup(self, system: str, code: str) -> dict[str, str] | None:
        if system in ("snomed", "icd11", "loinc"):
            r = self.client.get(f"{TX}/CodeSystem/$lookup",
                                params={"system": SYSTEMS[system], "code": code}, headers=_FHIR)
            if r.status_code != 200:
                return None
            params = {p["name"]: p.get("valueString") for p in r.json().get("parameter", [])}
            if not params.get("display"):
                return None
            return {"display": str(params["display"]), "version": str(params.get("version")),
                    "via": "tx.fhir.org"}
        if system == "atc":
            # The index page of the parent level lists its children: A, A01, A01A, A01AA, A01AA01.
            parent_length = {1: 1, 3: 1, 4: 3, 5: 4, 7: 5}.get(len(code), len(code))
            group = code[:parent_length]
            names = self._atc_group(group)
            return ({"display": names[code], "version": "", "via": "atcddd.fhi.no"}
                    if code in names else None)
        if system == "rxnorm":
            r = self.client.get(f"https://rxnav.nlm.nih.gov/REST/rxcui/{code}/properties.json")
            props = r.json().get("properties") if r.status_code == 200 else None
            return ({"display": props["name"], "version": "", "via": "rxnav.nlm.nih.gov"}
                    if props else None)
        if system in ("hpo", "uberon"):
            name = self._obo_terms(system).get(code)
            return {"display": name, "version": "", "via": "obo"} if name else None
        raise ValueError(f"no lookup for code system {system}")

    def _atc_group(self, group: str) -> dict[str, str]:
        key = f"atc-group|{group}"
        if key not in self.cache:
            r = self.client.get("https://atcddd.fhi.no/atc_ddd_index/",
                                params={"code": group, "showdescription": "no"})
            text = r.content.decode("latin-1")
            self.cache[key] = {c: html.unescape(n).strip() for c, n in
                               re.findall(r"code=([A-Z0-9]+)&[^>]*>([^<]+)</a>", text)}
        names: dict[str, str] = self.cache[key]
        return names

    def _obo_terms(self, system: str) -> dict[str, str]:
        if system not in self._obo:
            path = ONTOLOGIES / ("hp.obo" if system == "hpo" else "uberon-basic.obo")
            terms: dict[str, str] = {}
            term_id = None
            with path.open(encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("id: "):
                        term_id = line[4:].strip()
                    elif line.startswith("name: ") and term_id:
                        terms[term_id] = line[6:].strip()
                        term_id = None
            self._obo[system] = terms
        return self._obo[system]

    # Search (authoring aid) ---------------------------------------------------------------
    def search(self, system: str, text: str, count: int = 10) -> list[tuple[str, str]]:
        if system == "loinc":
            r = self.client.get("https://clinicaltables.nlm.nih.gov/api/loinc_items/v3/search",
                                params={"terms": text, "maxList": count,
                                        "df": "LOINC_NUM,LONG_COMMON_NAME"})
            r.raise_for_status()
            return [(row[0], row[1]) for row in r.json()[3]]
        if system in ("snomed", "icd11"):
            body = {"resourceType": "Parameters", "parameter": [
                {"name": "valueSet", "resource": {
                    "resourceType": "ValueSet", "status": "active",
                    "compose": {"include": [{"system": SYSTEMS[system]}]}}},
                {"name": "filter", "valueString": text},
                {"name": "count", "valueInteger": count}]}
            r = self.client.post(f"{TX}/ValueSet/$expand", json=body,
                                 headers={**_FHIR, "Content-Type": "application/fhir+json"})
            r.raise_for_status()
            return [(c["code"], c.get("display", ""))
                    for c in r.json().get("expansion", {}).get("contains", [])]
        if system in ("hpo", "uberon"):
            words = text.lower().split()
            return [(k, v) for k, v in self._obo_terms(system).items()
                    if all(w in v.lower() for w in words)][:count]
        if system == "rxnorm":
            r = self.client.get("https://rxnav.nlm.nih.gov/REST/rxcui.json", params={"name": text})
            ids = r.json().get("idGroup", {}).get("rxnormId", [])
            return [(i, text) for i in ids]
        if system == "atc":
            return list(self._atc_group(text.upper()).items())
        raise ValueError(f"no search for code system {system}")


def codes_in(obj: Any) -> Iterator[tuple[str, str]]:
    """Every (system, code) under a key named after a code system."""
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            if k in CODE_KEYS:
                for code in v if isinstance(v, list) else [v]:
                    if isinstance(code, str) and code:
                        yield k, code
            else:
                yield from codes_in(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from codes_in(v)


def kb_codes(kb: KnowledgeBase) -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for eid in kb.ids():
        for system, code in codes_in(kb.entry(eid).content()):
            found.setdefault(system, set()).add(code)
    return found


REGISTRY = ROOT / "ahdt" / "registry"


def registry_codes(directory: Path = REGISTRY) -> dict[str, set[str]]:
    """Codes on the twin definitions (design 03, 3.2), which also go in the code tables."""
    import yaml

    found: dict[str, set[str]] = {}
    for path in sorted(directory.glob("*.yaml")):
        with path.open(encoding="utf-8") as fh:
            for system, code in codes_in(yaml.safe_load(fh)):
                found.setdefault(system, set()).add(code)
    return found


def read_table(system: str, directory: Path = TERMINOLOGY) -> dict[str, dict[str, str]]:
    path = directory / f"{system}.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {row["code"]: row for row in csv.DictReader(fh)}


def verify(kb_dir: Path = ROOT / "kb") -> dict[str, list[str]]:
    """Look up every kb code, rewrite the code tables, and return the unknown codes by system."""
    term = Terminology()
    unknown: dict[str, list[str]] = {}
    TERMINOLOGY.mkdir(parents=True, exist_ok=True)
    try:
        wanted = kb_codes(KnowledgeBase(kb_dir))
        for system, codes in registry_codes().items():
            wanted.setdefault(system, set()).update(codes)
        for system, codes in sorted(wanted.items()):
            rows = read_table(system)
            for code in sorted(codes):
                found = term.lookup(system, code)
                if found is None:
                    unknown.setdefault(system, []).append(code)
                    continue
                rows[code] = {"code": code, **found}
            with (TERMINOLOGY / f"{system}.csv").open("w", encoding="utf-8", newline="") as fh:
                writer = csv.DictWriter(fh, fieldnames=["code", "display", "version", "via"])
                writer.writeheader()
                for code in sorted(rows):
                    writer.writerow({k: rows[code].get(k, "") for k in writer.fieldnames})
    finally:
        term.save()
    return unknown
