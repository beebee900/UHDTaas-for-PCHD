"""Structural checks of the kb (design 06, 6.3.3 step 7).

- every provenance citation names a source in `sources.yaml`
- every reference between entries resolves, to an entry of the expected kind
- every `threshold` + `path` lookup resolves to a number
- every code is in its `kb/terminology` table (written by `sourcing verify-codes`)
- an entry marked verified or approved still passes the number check
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any

from apdt.knowledge.numcheck import check_entry
from apdt.knowledge.sources import load_sources
from apdt.knowledge.terminology import codes_in, read_table
from atra.config import ROOT
from atra.kb import KnowledgeBase

# Field name → id prefixes the referenced entry may have.
REFERENCE_FIELDS: Mapping[str, tuple[str, ...]] = {
    "condition": ("cond.",),
    "regimen": ("dose.",),
    "combined_with": ("dose.",),
    "exclusions": ("ix.",),
    "adjustments": ("ix.",),
    "severity_rule": ("severity.",),
    "red_flags": ("find.",),
    "with_any": ("find.",),
    "complications_any": ("find.",),
    "finding": ("find.",),
    "threshold": ("threshold.", "severity.", "range.", "news2.", "pews."),
}


def _references(obj: Any, path: str = "") -> Iterator[tuple[str, str, str]]:
    """(field, path, referenced id) for every reference field below `obj`."""
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            if k in REFERENCE_FIELDS:
                for ref in v if isinstance(v, list) else [v]:
                    if isinstance(ref, str):
                        yield k, here, ref
            else:
                yield from _references(v, here)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _references(v, f"{path}[{i}]")


def _lookups(obj: Any, path: str = "") -> Iterator[tuple[str, str, str]]:
    """(path, entry id, sub-path) for every mapping that pairs `threshold` with `path`."""
    if isinstance(obj, Mapping):
        if isinstance(obj.get("threshold"), str) and isinstance(obj.get("path"), str):
            yield path, obj["threshold"], obj["path"]
        for k, v in obj.items():
            yield from _lookups(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from _lookups(v, f"{path}[{i}]")


def problems(kb_dir: Path = ROOT / "kb") -> list[str]:
    kb = KnowledgeBase(kb_dir)
    sources = load_sources(kb_dir / "sources.yaml")
    found: list[str] = []
    tables = {}
    for eid in kb.ids():
        entry = kb.entry(eid)
        content = entry.content()
        for cite in entry.provenance.citations():
            if cite.source not in sources:
                found.append(f"{eid}: source {cite.source} is not in sources.yaml")
        for field, path, ref in _references(content):
            prefixes = REFERENCE_FIELDS[field]
            if not ref.startswith(prefixes):
                found.append(f"{eid}: {path} = {ref} is not a {'/'.join(prefixes)} entry")
            elif ref not in kb:
                found.append(f"{eid}: {path} = {ref} is not a kb entry")
        for path, ref, sub in _lookups(content):
            if ref in kb:
                try:
                    value = kb.lookup(ref, sub)
                except KeyError:
                    found.append(f"{eid}: {path} = {ref} {sub} does not resolve")
                    continue
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    found.append(f"{eid}: {path} = {ref} {sub} is not a number")
        for system, code in codes_in(content):
            if system not in tables:
                tables[system] = read_table(system, kb_dir / "terminology")
            if code not in tables[system]:
                found.append(f"{eid}: {system} code {code} is not verified (run verify-codes)")
        if entry.provenance.status in ("verified", "approved"):
            rel = str(kb.path_of(eid).relative_to(kb_dir))
            if check_entry(entry, rel, sources).outcome == "fail":
                found.append(f"{eid}: marked {entry.provenance.status} but fails the number check")
    return found


def drafts(kb_dir: Path = ROOT / "kb") -> list[str]:
    return sorted(KnowledgeBase(kb_dir).drafts())
