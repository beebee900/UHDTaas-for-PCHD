"""`docs/governance/kb_review.pdf`: every kb entry with its source and page, assumptions
first, for the clinical sign-off (design 06, 6.3.3 step 6; P12).

The document is written as HTML and printed to PDF with headless Chromium (Playwright).
The HTML is kept next to the PDF so the reviewer can search it.
"""

from __future__ import annotations

import html
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from apdt.knowledge.numcheck import Finding, check_kb
from apdt.knowledge.sources import load_sources
from atra.config import ROOT
from atra.kb import KnowledgeBase

OUT_DIR = ROOT / "docs" / "governance"
HIGH_RISK = ("treatments/", "doses/", "interactions.yaml", "severity/", "critical_values.yaml")
CSS = """
body { font-family: 'DejaVu Sans', Arial, sans-serif; font-size: 9pt; color: #111; }
h1 { font-size: 16pt; } h2 { font-size: 12pt; margin-top: 18pt; border-bottom: 1px solid #999; }
h3 { font-size: 10pt; margin: 10pt 0 2pt; }
table { border-collapse: collapse; width: 100%; margin: 4pt 0; }
td, th { border: 1px solid #bbb; padding: 2pt 4pt; vertical-align: top; text-align: left; }
th { background: #eee; }
pre { font-family: 'DejaVu Sans Mono', monospace; font-size: 7.5pt; white-space: pre-wrap;
      margin: 2pt 0; background: #f7f7f7; padding: 3pt; }
.flag { background: #fff3cd; } .fail { background: #f8d7da; }
.sign { margin-top: 24pt; } .sign td { height: 28pt; }
"""


def _e(text: Any) -> str:
    return html.escape(str(text))


def _content_yaml(content: dict[str, Any]) -> str:
    text: str = yaml.safe_dump(content, sort_keys=False, allow_unicode=True, width=110)
    return text.strip()


def _citations(entry: Any, sources: dict[str, Any]) -> str:
    rows = []
    for c in entry.provenance.citations():
        src = sources.get(c.source)
        title = f"{src.title} ({src.publisher}, {src.year})" if src else c.source
        rows.append(f"{_e(title)}; section: {_e(c.section or '-')}; page: {_e(c.page or '-')}")
    return "<br>".join(rows) or "<em>none</em>"


def build_html(kb_dir: Path = ROOT / "kb") -> str:
    kb = KnowledgeBase(kb_dir)
    sources = load_sources(kb_dir / "sources.yaml")
    findings: dict[str, Finding] = {f.entry_id: f for f in check_kb(kb_dir).findings}
    by_file: dict[str, list[str]] = {}
    for eid in kb.ids():
        by_file.setdefault(str(kb.path_of(eid).relative_to(kb_dir)), []).append(eid)
    outcomes = Counter(f.outcome for f in findings.values())
    assumptions = [eid for eid in kb.ids() if kb.entry(eid).provenance.assumption]

    parts = [f"<html><head><meta charset='utf-8'><style>{CSS}</style></head><body>",
             "<h1>ATRA Health knowledge base: clinical review</h1>",
             f"<p>Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC from <code>kb/</code>. "
             f"{len(kb.ids())} entries in {len(by_file)} files, citing {len(sources)} sources.</p>",
             "<p>Every number in a sourced entry was checked automatically against the cited "
             "section and page. Entries marked as assumptions have no guideline source and carry "
             "the builder's justification. High-risk files (treatments, doses, interactions, "
             "severity, critical values) need a clinician's initials per entry.</p>",
             "<table><tr><th>Number check</th><th>Entries</th></tr>"]
    for o in ("pass", "assumption", "fail"):
        parts.append(f"<tr><td>{o}</td><td>{outcomes.get(o, 0)}</td></tr>")
    parts.append("</table>")

    parts.append(f"<h2>1. Assumptions to confirm ({len(assumptions)})</h2>"
                 "<table><tr><th>Entry</th><th>File</th><th>Justification</th><th>Decision</th></tr>")
    for eid in assumptions:
        e = kb.entry(eid)
        parts.append(f"<tr class='flag'><td>{_e(eid)}</td>"
                     f"<td>{_e(kb.path_of(eid).relative_to(kb_dir))}</td>"
                     f"<td>{_e(e.provenance.justification)}</td><td></td></tr>")
    parts.append("</table>")

    parts.append("<h2>2. Entries by file</h2>")
    for file in sorted(by_file, key=lambda f: (not f.startswith(HIGH_RISK), f)):
        risk = " (high risk: initial each entry)" if file.startswith(HIGH_RISK) else ""
        parts.append(f"<h3>{_e(file)}{risk}</h3>")
        for eid in by_file[file]:
            e = kb.entry(eid)
            f = findings.get(eid)
            cls = "fail" if f and f.outcome == "fail" else "flag" if e.provenance.assumption else ""
            check = f"{f.outcome}, {f.checked} numbers" if f else "-"
            parts.append(
                f"<table class='{cls}'><tr><th style='width:22%'>{_e(eid)}</th>"
                f"<td>status: {_e(e.provenance.status)}; check: {_e(check)}</td>"
                f"<td style='width:12%'>Initials:</td></tr>"
                f"<tr><td colspan='3'>{_citations(e, sources)}"
                f"<pre>{_e(_content_yaml(e.content()))}</pre></td></tr></table>")

    parts.append("<h2>3. Sources</h2><table><tr><th>Id</th><th>Title</th><th>Publisher</th>"
                 "<th>Year</th><th>Licence</th></tr>")
    for s in sources.values():
        parts.append(f"<tr><td>{_e(s.id)}</td><td>{_e(s.title)}</td><td>{_e(s.publisher)}</td>"
                     f"<td>{_e(s.year or '')}</td><td>{_e(s.licence or '')}</td></tr>")
    parts.append("</table>")
    parts.append("<h2>4. Sign-off</h2><table class='sign'><tr><th>Reviewer</th><th>Role</th>"
                 "<th>Signature</th><th>Date</th></tr><tr><td></td><td></td><td></td><td></td>"
                 "</tr></table></body></html>")
    return "\n".join(parts)


def write_review(out_dir: Path = OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    page = out_dir / "kb_review.html"
    page.write_text(build_html(), encoding="utf-8")
    pdf = out_dir / "kb_review.pdf"
    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            tab = browser.new_page()
            tab.goto(page.as_uri(), wait_until="load")
            tab.pdf(path=str(pdf), format="A4", print_background=True,
                    margin={"top": "15mm", "bottom": "15mm", "left": "12mm", "right": "12mm"})
        finally:
            browser.close()
    return pdf
