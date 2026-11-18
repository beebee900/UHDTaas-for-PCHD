"""Download every located source and lock its hash (design 06, 6.3.3 step 1)."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from apdt.knowledge.sources import (
    STORE,
    LockEntry,
    Source,
    load_lock,
    load_sources,
    save_lock,
    sha256_file,
)

USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) atra-health-kb/0.1"

# CPIC tables kept for the genes the kb uses.
CPIC_GENES = ("CYP2D6", "CYP2C19", "CYP2B6", "CYP2C9", "G6PD")


def _cpic_bundle(client: httpx.Client, base: str) -> dict[str, Any]:
    genes = ",".join(CPIC_GENES)

    def get(table: str, query: str) -> Any:
        r = client.get(f"{base}{table}?{query}")
        r.raise_for_status()
        return r.json()

    pairs = get("pair", f"genesymbol=in.({genes})&removed=eq.false")
    guideline_ids = sorted({p["guidelineid"] for p in pairs if p["guidelineid"]})
    drug_ids = sorted({p["drugid"] for p in pairs})
    in_guidelines = ",".join(str(g) for g in guideline_ids)
    in_drugs = ",".join(f'"{d}"' for d in drug_ids)
    return {
        "fetched_from": base,
        "genes": list(CPIC_GENES),
        "allele": get("allele", f"genesymbol=in.({genes})&select=genesymbol,name,"
                      "clinicalfunctionalstatus,activityvalue,citations"),
        "gene_result": get("gene_result", f"genesymbol=in.({genes})"),
        "pair": pairs,
        "guideline": get("guideline", f"id=in.({in_guidelines})"),
        "drug": get("drug", f"drugid=in.({in_drugs})"),
        "recommendation": get("recommendation", f"guidelineid=in.({in_guidelines})"),
    }


def _pdf_title(path: Path) -> str | None:
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(path)
    try:
        title = pdf.get_metadata_dict().get("Title")
        if not title and len(pdf) > 0:
            text = pdf[0].get_textpage().get_text_range()
            title = " ".join(text.split())[:160]
        return title or None
    finally:
        pdf.close()


def _check_payload(src: Source, path: Path, content_type: str) -> None:
    head = path.read_bytes()[:1024]
    expected = {
        "pdf": head.startswith(b"%PDF"),
        "jats": b"<article" in head or b"<?xml" in head,
        "json": head.lstrip()[:1] in (b"{", b"["),
        "html": b"<html" in head.lower() or b"<!doctype" in head.lower(),
    }
    if src.format and not expected[src.format]:
        raise ValueError(f"{src.id}: response is not {src.format} ({content_type})")


def fetch(ids: list[str] | None = None, refresh: bool = False) -> dict[str, str]:
    """Fetch the given (or every) located source. Returns id → outcome."""
    sources = load_sources()
    lock = load_lock()
    STORE.mkdir(parents=True, exist_ok=True)
    outcome: dict[str, str] = {}
    with httpx.Client(follow_redirects=True, timeout=180,
                      headers={"User-Agent": USER_AGENT}) as client:
        for src in sources.values():
            if ids and src.id not in ids:
                continue
            path = src.path
            if src.status != "located" or path is None:
                continue
            if (not refresh and src.id in lock and path.exists()
                    and sha256_file(path) == lock[src.id].sha256):
                outcome[src.id] = "unchanged"
                continue
            assert src.url is not None
            try:
                content_type = ""
                if src.id == "cpic-api":
                    path.write_text(json.dumps(_cpic_bundle(client, src.url), indent=1),
                                    encoding="utf-8")
                    content_type = "application/json"
                else:
                    with client.stream("GET", src.url) as r:
                        r.raise_for_status()
                        content_type = r.headers.get("content-type", "")
                        with path.open("wb") as fh:
                            for chunk in r.iter_bytes():
                                fh.write(chunk)
                _check_payload(src, path, content_type)
            except (httpx.HTTPError, ValueError) as exc:
                path.unlink(missing_ok=True)
                outcome[src.id] = f"failed: {exc}"
                continue
            title = _pdf_title(path) if src.format == "pdf" else None
            lock[src.id] = LockEntry(bytes=path.stat().st_size, sha256=sha256_file(path),
                                     accessed=datetime.now(UTC).date(),
                                     content_type=content_type.split(";")[0] or None,
                                     title_found=_clean(title))
            outcome[src.id] = f"fetched {path.stat().st_size} bytes"
    save_lock(lock)
    return outcome


def _clean(text: str | None) -> str | None:
    return re.sub(r"\s+", " ", text).strip() if text else None
