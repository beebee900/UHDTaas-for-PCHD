"""Fetch the approved open datasets and record their checksums (design 08, WP02 step 1).

    python -m evaluation.datasets.fetch [ids...]      approved datasets only
    python -m evaluation.datasets.fetch --list
    python -m evaluation.datasets.fetch --doc         regenerate docs/governance/datasets.md

Files go to `var/datasets/<id>/`; `evaluation/datasets/datasets.lock.yaml` keeps the size,
SHA-256 and access date of each download. A dataset is fetched only when its entry says
`status: approved`.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import yaml

from atra.config import ROOT

HERE = Path(__file__).resolve().parent
REGISTRY = HERE / "datasets.yaml"
LOCK = HERE / "datasets.lock.yaml"
STORE = ROOT / "var" / "datasets"
USER_AGENT = "atra-health-datasets/0.1 (research build; https://github.com/lazy-monster/dyon)"


def load() -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = yaml.safe_load(REGISTRY.read_text())
    return entries


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fetch(ids: list[str]) -> dict[str, str]:
    lock = yaml.safe_load(LOCK.read_text()) if LOCK.exists() else {}
    out = {}
    for d in load():
        if ids and d["id"] not in ids:
            continue
        if d["status"] != "approved" or not d.get("url"):
            out[d["id"]] = f"skipped ({d['status']})"
            continue
        target = STORE / d["id"] / Path(d["url"]).name
        target.parent.mkdir(parents=True, exist_ok=True)
        with httpx.stream("GET", d["url"], follow_redirects=True, timeout=600,
                          headers={"User-Agent": USER_AGENT}) as r:
            r.raise_for_status()
            with target.open("wb") as fh:
                for chunk in r.iter_bytes(1 << 20):
                    fh.write(chunk)
        lock[d["id"]] = {"bytes": target.stat().st_size, "sha256": _sha256(target),
                         "accessed": datetime.now(UTC).date().isoformat()}
        out[d["id"]] = f"fetched {lock[d['id']]['bytes']} bytes"
    LOCK.write_text(yaml.safe_dump(lock, sort_keys=True))
    return out


DOC = ROOT / "docs" / "governance" / "datasets.md"


def doc() -> str:
    lines = ["# Open datasets", "",
             "Generated from `evaluation/datasets/datasets.yaml` by "
             "`python -m evaluation.datasets.fetch --doc`. A dataset is used only after its "
             "status is `approved`.", "",
             "| Dataset | Use | Size | Licence | Status | Citation |",
             "|---|---|---|---|---|---|"]
    for d in load():
        size = f"{d['bytes'] / 1e6:,.0f} MB" if d.get("bytes") else "not stated"
        title = f"[{d['title']}]({d['landing']})" if d.get("landing") else d["title"]
        lines.append(f"| {title} | {d['use']} | {size} | {d.get('licence') or 'to confirm'} "
                     f"| {d['status']} | {d.get('citation') or ''} |")
    notes = [f"- {d['id']}: {d['note']}" for d in load() if d.get("note")]
    return "\n".join([*lines, "", "Notes:", "", *notes, ""])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evaluation.datasets.fetch")
    parser.add_argument("ids", nargs="*")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--doc", action="store_true")
    args = parser.parse_args(argv)
    if args.doc:
        DOC.write_text(doc(), encoding="utf-8")
        print(f"wrote {DOC}")
        return 0
    if args.list:
        for d in load():
            size = f"{d['bytes'] / 1e6:,.0f} MB" if d.get("bytes") else "size unknown"
            print(f"{d['id']:20} {d['status']:9} {size:>12}  {d['licence']}")
        return 0
    for key, outcome in fetch(args.ids).items():
        print(f"{key}: {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
