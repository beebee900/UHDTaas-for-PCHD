"""Automated second pass over the kb (design 06, 6.3.3 step 4).

Every number in an entry must appear in the text its provenance cites: the cited section with
its subsections, or the cited PDF page and the page after it (tables run over page breaks).
Numbers named in `provenance.derived` are exempt and listed with their derivation in the review.
Assumption entries are not checked; they need a justification and are listed for sign-off.
When an entry carries a `unit`, a missing unit in the cited text is a warning, not a failure.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator
from dataclasses import dataclass, field
from functools import cache
from pathlib import Path
from typing import Any, Literal

from apdt.knowledge.sections import SectionTree, load_tree, tree_path
from apdt.knowledge.sources import Source, load_lock, load_sources, local_copy
from atra.config import ROOT
from atra.kb import Citation, Entry, KnowledgeBase

KB_DIR = ROOT / "kb"

type Outcome = Literal["pass", "fail", "assumption"]

# Symbol glyphs such as ≥ often extract as a letter glued to the number ("X26.5").
_NUM = re.compile(r"(?<![\d.])-?\d+(?:\.\d+)?(?!\d)")
_UNIT_ALIASES: dict[str, tuple[str, ...]] = {
    "mm[Hg]": ("mmhg", "mm hg"),
    "/min": ("/min", "per minute", "bpm", "breaths", "beats"),
    "Cel": ("°c", "ºc", "celsius", "° c"),
    "%": ("%", "per cent", "percent"),
    "mmol/L": ("mmol/l", "mmol/ l"),
    "umol/L": ("µmol/l", "μmol/l", "umol/l"),
    "g/dL": ("g/dl",),
    "g/L": ("g/l",),
    "mg/dL": ("mg/dl",),
    "mL/min/{1.73_m2}": ("ml/min/1.73", "ml/min per 1.73"),
    "U/L": ("u/l", "iu/l"),
    "10*9/L": ("109/l", "10^9/l", "10⁹/l"),
}


@dataclass
class Finding:
    entry_id: str
    file: str
    outcome: Outcome
    checked: int = 0
    missing: list[tuple[str, float]] = field(default_factory=list)
    derived: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


@dataclass
class Report:
    findings: list[Finding]

    @property
    def ok(self) -> bool:
        return all(f.outcome != "fail" for f in self.findings)

    def by_outcome(self, outcome: Outcome) -> list[Finding]:
        return [f for f in self.findings if f.outcome == outcome]

    def summary_lines(self) -> Iterator[str]:
        for f in self.by_outcome("fail"):
            detail = "; ".join(f.errors + [f"{p}={v:g} not in cited text" for p, v in f.missing])
            yield f"FAIL {f.file} {f.entry_id}: {detail}"
        outcomes: tuple[Outcome, ...] = ("pass", "fail", "assumption")
        counts = {o: len(self.by_outcome(o)) for o in outcomes}
        warned = sum(1 for f in self.findings if f.warnings)
        checked = sum(f.checked for f in self.findings)
        yield (f"{counts['pass']} pass, {counts['fail']} fail, {counts['assumption']} assumption, "
               f"{warned} with warnings, {checked} numbers checked")


def numbers_in(obj: Any, path: str = "") -> Iterator[tuple[str, float]]:
    """Every numeric leaf of an entry's content with its dotted path."""
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, int | float):
        yield path, float(obj)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from numbers_in(v, f"{path}.{k}" if path else str(k))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from numbers_in(v, f"{path}[{i}]")


def normalise(text: str) -> str:
    for old, new in (("·", "."), ("−", "-"), ("–", " - "), (" ", " "), (" ", " ")):
        text = text.replace(old, new)
    return re.sub(r"(?<=\d),(?=\d{3}\b)", "", text)


_SPACE_GROUPED = re.compile(r"(?<![\d.])\d{1,3}(?: \d{3})+(?![\d.])")


def text_numbers(text: str) -> set[float]:
    """Every number in the text; "10 000" also counts as 10000."""
    text = normalise(text)
    found = {abs(float(m.group(0))) for m in _NUM.finditer(text)}
    found |= {float(m.group(0).replace(" ", "")) for m in _SPACE_GROUPED.finditer(text)}
    return found


@cache
def _tree(source_id: str) -> SectionTree | None:
    return load_tree(source_id) if tree_path(source_id).exists() else None


@cache
def _cpic() -> dict[str, Any]:
    sources = load_sources()
    path: Path = local_copy(sources["cpic-api"], sources, load_lock())
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


@cache
def _terminology_text() -> str:
    from apdt.knowledge.terminology import TERMINOLOGY

    return " ".join(p.read_text(encoding="utf-8") for p in sorted(TERMINOLOGY.glob("*.csv")))


def cited_text(cite: Citation, sources: dict[str, Source]) -> tuple[str, list[str]]:
    """The text a citation points at, and the problems found resolving it."""
    src = sources.get(cite.source)
    if src is None:
        return "", [f"source {cite.source} is not in sources.yaml"]
    if src.status == "unavailable":
        return "", [f"source {cite.source} has no retrievable full text"]
    if src.format == "terminology":
        return _terminology_text(), []
    if src.data_via == "cpic-api" or src.id == "cpic-api":
        table, _, key = (cite.section or "").partition(":")
        table, key = table.strip(), key.strip()
        records = _cpic().get(table, [])
        keys = {key}
        if table == "recommendation":
            keys |= {d["drugid"] for d in _cpic()["drug"] if d["name"] == key}
        hits = [r for r in records
                if key and any(k in json.dumps(r, ensure_ascii=False) for k in keys)]
        if not hits:
            return "", [f"no CPIC {table.strip()} records for '{key}'"]
        return json.dumps(hits, ensure_ascii=False), []
    tree = _tree(src.id)
    if tree is None:
        return "", [f"no section tree for {src.id}"]
    parts: list[str] = []
    if cite.section:
        for sec in tree.find(cite.section):
            parts.extend(s.text for s in tree.descendants(sec.id))
    if cite.page:
        parts.extend(tree.page_text(p) for p in (cite.page, cite.page + 1))
    if not parts:
        return "", [f"section '{cite.section}' page {cite.page} not found in {src.id}"]
    return " ".join(parts), []


def derived_match(pattern: str, path: str) -> bool:
    """Match a `derived` key against a value path; only `*` is a wildcard."""
    rx = re.escape(pattern).replace(r"\*", ".*")
    return re.fullmatch(rx, path) is not None


def _expects_numbers(content: dict[str, Any]) -> bool:
    return any(k in content for k in ("value", "ref_low", "ref_high", "normal"))


def check_entry(entry: Entry, file: str, sources: dict[str, Source]) -> Finding:
    prov = entry.provenance
    content = entry.content()
    if prov.assumption:
        finding = Finding(entry.id, file, "assumption")
        if _expects_numbers(content) and not any(True for _ in numbers_in(content)):
            finding.warnings.append("assumption without a value")
        return finding
    finding = Finding(entry.id, file, "pass", derived=dict(prov.derived))
    citations = prov.citations()
    if not citations:
        finding.outcome = "fail"
        finding.errors.append("no source and not an assumption")
        return finding
    texts: list[str] = []
    for cite in citations:
        text, problems = cited_text(cite, sources)
        texts.append(text)
        finding.errors.extend(problems)
    corpus = " ".join(texts)
    available = text_numbers(corpus)
    for path, value in numbers_in(content):
        if any(derived_match(pattern, path) for pattern in prov.derived):
            continue
        finding.checked += 1
        if not any(abs(abs(value) - t) <= 1e-9 * max(1.0, t) for t in available):
            finding.missing.append((path, value))
    unit = content.get("unit")
    if isinstance(unit, str) and unit in _UNIT_ALIASES and corpus:
        low = normalise(corpus).lower()
        if not any(alias in low for alias in _UNIT_ALIASES[unit]):
            finding.warnings.append(f"unit {unit} not found in cited text")
    if finding.missing or finding.errors:
        finding.outcome = "fail"
    return finding


def check_kb(kb_dir: Path = KB_DIR) -> Report:
    kb = KnowledgeBase(kb_dir)
    sources = load_sources(kb_dir / "sources.yaml")
    findings = [check_entry(kb.entry(eid), str(kb.path_of(eid).relative_to(kb_dir)), sources)
                for eid in kb.ids()]
    return Report(findings)


_ID = re.compile(r"^- id: ['\"]?([^'\"\s]+)['\"]?\s*$")
_STATUS = re.compile(r"^(\s+)status: (draft|verified|approved)\s*$")
_VERIFIED_BY = re.compile(r"^\s+verified_by: .*$")


def promote(report: Report, kb_dir: Path = KB_DIR) -> None:
    """Write each outcome back: `verified` for pass and assumption, `draft` for fail.

    Approved entries (P12 sign-off) keep their status unless they now fail.
    """
    by_file: dict[str, dict[str, Finding]] = {}
    for f in report.findings:
        by_file.setdefault(f.file, {})[f.entry_id] = f
    for file, findings in by_file.items():
        path = kb_dir / file
        out: list[str] = []
        current: Finding | None = None
        for line in path.read_text(encoding="utf-8").splitlines():
            m_id = _ID.match(line)
            if m_id:
                current = findings.get(m_id.group(1))
            if current is not None and _VERIFIED_BY.match(line):
                continue
            m = _STATUS.match(line)
            if current is not None and m:
                indent, old = m.groups()
                if current.outcome == "fail":
                    out.append(f"{indent}status: draft")
                    continue
                by = "second_pass" if current.outcome == "pass" else "assumption_listed"
                out.append(f"{indent}verified_by: {by}")
                out.append(f"{indent}status: {'approved' if old == 'approved' else 'verified'}")
                continue
            out.append(line)
        path.write_text("\n".join(out) + "\n", encoding="utf-8")
