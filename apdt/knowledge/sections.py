"""Section trees of the kb sources (design 06, 6.3.3 step 2).

A tree is a flat list of sections in reading order. Each section has a title, a number when the
heading carries one, a level, a parent and its own text, with the PDF page (1-based) of every
line. Citations, the number check and chunkless retrieval all read these trees.

PDF text comes from docling-parse line cells. Headings come from the PDF outline when it is
usable, else from the line typography: larger than body text, bold, or a different font family,
short, and not a sentence. Running headers and footers (lines repeated on many pages) are dropped.
JATS articles use their `<sec>` structure and HTML pages their `<h1>`–`<h6>` tags.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from apdt.knowledge.sources import STORE, LockEntry, Source

TREES = STORE.parent / "kb_sections"

_NUMBERED = re.compile(r"^((?:\d+|[A-Z])(?:\.\d+)*)\.?\s+(?=\S)")
_BOLD = re.compile(r"bold|black|heavy|semibold|demi|_b\b|-b\b|\+b\b", re.I)
_FAMILY = re.compile(r"^/?[A-Z]{6}\+|[-,_](bold|italic|regular|roman|rm|it|b|light|medium)\w*$",
                     re.I)


class Line(BaseModel):
    page: int
    text: str


class Section(BaseModel):
    id: str
    number: str | None
    title: str
    level: int
    parent: str | None
    page_start: int
    page_end: int
    lines: list[Line]

    @property
    def text(self) -> str:
        return " ".join([self.title, *(line.text for line in self.lines)])


class SectionTree(BaseModel):
    source: str
    sha256: str
    pages: int
    method: str
    sections: list[Section]

    def by_id(self, section_id: str) -> Section:
        for s in self.sections:
            if s.id == section_id:
                return s
        raise KeyError(section_id)

    def descendants(self, section_id: str) -> list[Section]:
        out: list[Section] = []
        wanted = {section_id}
        for s in self.sections:
            if s.id in wanted or s.parent in wanted:
                wanted.add(s.id)
                out.append(s)
        return out

    def page_text(self, page: int) -> str:
        parts: list[str] = []
        for s in self.sections:
            if s.page_start == page and s.id != "s0":
                parts.append(s.title)
            parts.extend(ln.text for ln in s.lines if ln.page == page)
        return " ".join(parts)

    def find(self, cite: str) -> list[Section]:
        """Sections matching a citation: a heading number, a table/figure label or title words."""
        cite = cite.strip()
        number = _NUMBERED.match(cite + " ")
        if number:
            hits = [s for s in self.sections if s.number == number.group(1)]
            if hits:
                return hits
        label = re.match(r"^(table|figure|box|annex|chart)\s+([\w.]+)", cite, re.I)
        if label:
            key = f"{label.group(1).lower()} {label.group(2).rstrip('.').lower()}"
            hits = [s for s in self.sections
                    if key in s.title.lower() or key in s.text[:4000].lower()]
            if hits:
                return hits
        words = _words(cite)
        if not words:
            return []
        scored = [(len(words & _words(s.title)) / len(words), s) for s in self.sections]
        best = max((sc for sc, _ in scored), default=0.0)
        return [s for sc, s in scored if sc >= 0.6 and sc == best]


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


@dataclass
class _Raw:
    page: int
    text: str
    height: float
    font: str
    heading: bool = False
    level: int = 0
    number: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)


def _family(font: str) -> str:
    name = font.split("+", 1)[-1]
    return _FAMILY.sub("", name).lower()


def _pdf_lines(path: Path) -> tuple[list[_Raw], int]:
    from docling_parse.pdf_parser import ContentConfig, ContentLevel, DoclingPdfParser

    # Line cells only; docling-parse caches every decoded page, so each page is released.
    lines_only = ContentConfig(
        char_cells_content_level=ContentLevel.COMPUTE,
        word_cells_content_level=ContentLevel.SKIP,
        line_cells_content_level=ContentLevel.COMPUTE_AND_MATERIALIZE,
        shapes_content_level=ContentLevel.SKIP,
        bitmaps_content_level=ContentLevel.SKIP,
        include_bitmap_bytes=False,
    )
    doc = DoclingPdfParser(loglevel="fatal").load(path_or_stream=str(path), lazy=True)
    lines: list[_Raw] = []
    pages = doc.number_of_pages()
    try:
        for pno in range(1, pages + 1):
            page = doc.get_page(pno, content_config=lines_only)
            for cell in page.textline_cells:
                text = " ".join(cell.text.split())
                if not text or all(not ch.isalnum() for ch in text):
                    continue
                r = cell.rect
                lines.append(_Raw(page=pno, text=text, height=round(abs(r.r_y2 - r.r_y0), 1),
                                  font=getattr(cell, "font_name", None) or ""))
            del page
            doc.unload_pages((pno, pno + 1))
    finally:
        doc.unload()
    return lines, pages


def _drop_running(lines: list[_Raw], pages: int) -> list[_Raw]:
    if pages < 6:
        return lines
    key = [re.sub(r"\d+", "#", ln.text.lower()) for ln in lines]
    per_page: dict[str, set[int]] = {}
    for k, ln in zip(key, lines, strict=True):
        per_page.setdefault(k, set()).add(ln.page)
    running = {k for k, pg in per_page.items() if len(pg) >= max(4, pages * 0.2)}
    return [ln for k, ln in zip(key, lines, strict=True) if k not in running]


def _mark_headings(lines: list[_Raw]) -> None:
    chars: Counter[tuple[float, str]] = Counter()
    for ln in lines:
        chars[(ln.height, _family(ln.font))] += len(ln.text)
    (body_h, body_family), _ = chars.most_common(1)[0]
    for i, ln in enumerate(lines):
        text = ln.text
        if len(text) > 110 or len(text) < 3 or not re.search(r"[A-Za-z]{3}", text):
            continue
        if text.endswith((".", ",", ";", ":")) and not _NUMBERED.match(text):
            continue
        if text[0].islower():
            continue
        bigger = ln.height >= body_h * 1.15
        bold = bool(_BOLD.search(ln.font))
        other = _family(ln.font) != body_family and ln.height >= body_h * 0.8
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        followed = nxt is not None and (nxt.height != ln.height or nxt.font != ln.font)
        if bigger or ((bold or other) and followed):
            ln.heading = True
    # Join headings broken over several lines.
    for i in range(len(lines) - 1, 0, -1):
        a, b = lines[i - 1], lines[i]
        if (a.heading and b.heading and a.page == b.page and a.height == b.height
                and a.font == b.font and not _NUMBERED.match(b.text)):
            a.text = f"{a.text} {b.text}"
            b.heading = False
            b.text = ""
    sizes = sorted({ln.height for ln in lines if ln.heading}, reverse=True)
    for ln in lines:
        if not ln.heading:
            continue
        m = _NUMBERED.match(ln.text)
        if m and not re.fullmatch(r"\d{3,}", m.group(1)):
            ln.number = m.group(1)
            ln.level = m.group(1).count(".") + 1
        else:
            ln.level = min(sizes.index(ln.height) + 1, 4)


def _apply_outline(lines: list[_Raw], toc: list[tuple[int, str, int]]) -> bool:
    """Mark the outline's headings on their pages. False when the outline is unusable."""
    toc = [(lvl, title, pg) for lvl, title, pg in toc
           if title and not title.startswith("_") and pg >= 1]
    if len(toc) < 8:
        return False
    by_page: dict[int, list[_Raw]] = {}
    for ln in lines:
        by_page.setdefault(ln.page, []).append(ln)
    for lvl, title, pg in toc:
        want = _words(title)
        target = None
        for ln in by_page.get(pg, []):
            if want and len(want & _words(ln.text)) / len(want) >= 0.6:
                target = ln
                break
        if target is None:
            first = by_page.get(pg)
            if not first:
                continue
            target = _Raw(page=pg, text="", height=0, font="")
            lines.insert(lines.index(first[0]), target)
            by_page[pg].insert(0, target)
        target.heading = True
        target.text = " ".join(title.split())
        target.level = lvl + 1
        m = _NUMBERED.match(target.text)
        target.number = m.group(1) if m else None
    return True


def _build(lines: Iterable[_Raw], source: str, sha: str, pages: int, method: str) -> SectionTree:
    sections: list[Section] = []
    stack: list[Section] = []
    current = Section(id="s0", number=None, title="(front matter)", level=0, parent=None,
                      page_start=1, page_end=1, lines=[])
    sections.append(current)
    for ln in lines:
        if not ln.text:
            continue
        if ln.heading:
            while stack and stack[-1].level >= ln.level:
                stack.pop()
            current = Section(id=f"s{len(sections)}", number=ln.number, title=ln.text,
                              level=ln.level, parent=stack[-1].id if stack else None,
                              page_start=ln.page, page_end=ln.page, lines=[])
            sections.append(current)
            stack.append(current)
            continue
        current.lines.append(Line(page=ln.page, text=ln.text))
        current.page_end = max(current.page_end, ln.page)
    return SectionTree(source=source, sha256=sha, pages=pages, method=method, sections=sections)


def pdf_tree(src: Source, path: Path, sha: str) -> SectionTree:
    import pypdfium2 as pdfium

    lines, pages = _pdf_lines(path)
    lines = _drop_running(lines, pages)
    pdf = pdfium.PdfDocument(path)
    try:
        toc = []
        for item in pdf.get_toc(max_depth=6):
            dest = item.get_dest()
            index = dest.get_index() if dest is not None else None
            toc.append((item.level, item.get_title(), (index if index is not None else -2) + 1))
    finally:
        pdf.close()
    if _apply_outline(lines, toc):
        method = "docling-parse+outline"
    else:
        _mark_headings(lines)
        method = "docling-parse+typography"
    return _build(lines, src.id, sha, pages, method)


_JATS_CONTAINERS = frozenset({"body", "abstract", "front", "article-meta", "back", "floats-group"})
# Metadata and reference lists; every other element's text is kept (boxed recommendations too).
_JATS_SKIP = frozenset({
    "title", "label", "ref-list", "journal-meta", "contrib-group", "aff", "pub-date",
    "permissions", "counts", "kwd-group", "history", "article-categories", "title-group",
    "author-notes", "funding-group", "custom-meta-group", "article-id", "self-uri",
    "related-article", "elocation-id", "volume", "issue", "fpage", "lpage",
    "supplementary-material", "fn-group", "ack", "notes", "trans-abstract",
})


def jats_tree(src: Source, path: Path, sha: str) -> SectionTree:
    from lxml import etree

    root = etree.parse(str(path)).getroot()
    raws: list[_Raw] = []

    def walk(node: Any, level: int) -> None:
        for child in node:
            if not isinstance(child.tag, str):
                continue
            tag = etree.QName(child).localname
            if tag == "sec":
                title = child.find("title")
                text = " ".join(" ".join(title.itertext()).split()) if title is not None else ""
                m = _NUMBERED.match(text)
                raws.append(_Raw(page=1, text=text or "(untitled)", height=0, font="",
                                 heading=True, level=level, number=m.group(1) if m else None))
                walk(child, level + 1)
            elif tag in {"table-wrap", "fig"}:
                label = child.find("label")
                caption = " ".join(" ".join(child.itertext()).split())
                name = "".join(label.itertext()) if label is not None else caption[:80] or tag
                raws.append(_Raw(page=1, text=name, height=0, font="", heading=True,
                                 level=level))
                raws.append(_Raw(page=1, text=caption, height=0, font=""))
            elif tag in _JATS_CONTAINERS:
                walk(child, level)
            elif tag not in _JATS_SKIP:
                text = " ".join(" ".join(child.itertext()).split())
                if text:
                    raws.append(_Raw(page=1, text=text, height=0, font=""))

    walk(root, 1)
    return _build(raws, src.id, sha, 1, "jats")


def html_tree(src: Source, path: Path, sha: str) -> SectionTree:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(path.read_text(encoding="utf-8", errors="replace"), "lxml")
    raws: list[_Raw] = []
    for el in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "tr"]):
        text = " ".join(el.get_text(" ").split())
        if not text:
            continue
        if el.name.startswith("h"):
            raws.append(_Raw(page=1, text=text, height=0, font="", heading=True,
                             level=int(el.name[1])))
        else:
            raws.append(_Raw(page=1, text=text, height=0, font=""))
    return _build(raws, src.id, sha, 1, "html")


def build_tree(src: Source, path: Path, lock: LockEntry) -> SectionTree:
    if src.format == "pdf":
        return pdf_tree(src, path, lock.sha256)
    if src.format == "jats":
        return jats_tree(src, path, lock.sha256)
    if src.format == "html":
        return html_tree(src, path, lock.sha256)
    raise ValueError(f"{src.id}: no section tree for format {src.format}")


def tree_path(source_id: str) -> Path:
    return TREES / f"{source_id}.json"


def load_tree(source_id: str) -> SectionTree:
    return SectionTree.model_validate_json(tree_path(source_id).read_text(encoding="utf-8"))


def save_tree(tree: SectionTree) -> Path:
    TREES.mkdir(parents=True, exist_ok=True)
    path = tree_path(tree.source)
    path.write_text(json.dumps(tree.model_dump(mode="json"), ensure_ascii=False),
                    encoding="utf-8")
    return path


def iter_trees(source_ids: Iterable[str]) -> Iterator[SectionTree]:
    for sid in source_ids:
        if tree_path(sid).exists():
            yield load_tree(sid)
