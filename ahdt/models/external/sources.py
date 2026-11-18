"""Pinned external model files and tools, kept under `var/wp14c/sources`.

`sources.lock.yaml` records the URL, size and sha256 of every file. A missing file is
downloaded once and verified; a file with another hash is rejected.
"""

from __future__ import annotations

import hashlib
import urllib.request
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from atra.config import ROOT

LOCK = Path(__file__).resolve().parent / "sources.lock.yaml"
USER_AGENT = "atra-health-wp14c/1.0"


class SourceError(RuntimeError):
    pass


def directory() -> Path:
    return ROOT / "var" / "wp14c" / "sources"


@cache
def lock() -> dict[str, dict[str, Any]]:
    with LOCK.open(encoding="utf-8") as fh:
        data: dict[str, dict[str, Any]] = yaml.safe_load(fh)
    return data


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fetch(source_id: str) -> Path:
    """The verified local path of a source, downloaded when it is missing."""
    entry = lock()[source_id]
    path = directory() / entry["file"]
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        request = urllib.request.Request(entry["url"], headers={"User-Agent": USER_AGENT})
        part = path.with_suffix(path.suffix + ".part")
        with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as out:
            for chunk in iter(lambda: response.read(1 << 20), b""):
                out.write(chunk)
        part.replace(path)
    if sha256_of(path) != entry["sha256"]:
        raise SourceError(f"{source_id}: {path.name} does not match the pinned sha256")
    return Path(path)


def available(source_id: str) -> bool:
    entry = lock()[source_id]
    path = directory() / entry["file"]
    return bool(path.exists() and sha256_of(path) == entry["sha256"])


def main() -> None:
    for source_id in lock():
        print(source_id, fetch(source_id))


if __name__ == "__main__":
    main()
