"""The kb source list (`kb/sources.yaml`) and the record of fetched copies (`kb/sources.lock.yaml`).

`sources.yaml` is written by hand. The lock file is written by `fetch` and records what was
retrieved: size, SHA-256 and access date. A source counts as fetched only when its local copy
matches the locked hash.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

from atra.config import ROOT

KB_DIR = ROOT / "kb"
SOURCES_FILE = KB_DIR / "sources.yaml"
LOCK_FILE = KB_DIR / "sources.lock.yaml"
STORE = ROOT / "var" / "kb_sources"

type Format = Literal["pdf", "jats", "json", "html", "terminology"]
_SUFFIX: dict[str, str] = {"pdf": "pdf", "jats": "xml", "json": "json", "html": "html"}


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    publisher: str
    year: int | None = None
    edition: str | None = None
    isbn: str | None = None
    doi: str | None = None
    landing: str | None = None
    url: str | None = None
    format: Format | None = None
    bytes: int | None = None
    licence: str | None = None
    pathways: list[str] = []
    data_via: str | None = None
    status: Literal["located", "unavailable"] = "located"
    note: str | None = None

    @model_validator(mode="after")
    def _retrievable(self) -> Source:
        if self.status == "located" and not (self.url or self.data_via):
            raise ValueError(f"{self.id}: a located source needs `url` or `data_via`")
        if self.status == "unavailable" and not self.note:
            raise ValueError(f"{self.id}: an unavailable source needs a `note`")
        return self

    @property
    def path(self) -> Path | None:
        fmt = self.format
        if self.url is None or fmt is None or fmt == "terminology":
            return None
        return STORE / f"{self.id}.{_SUFFIX[fmt]}"


class LockEntry(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bytes: int
    sha256: str
    accessed: date
    content_type: str | None = None
    title_found: str | None = None


def load_sources(path: Path = SOURCES_FILE) -> dict[str, Source]:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or []
    sources: dict[str, Source] = {}
    for item in raw:
        src = Source.model_validate(item)
        if src.id in sources:
            raise ValueError(f"source id {src.id} is listed twice")
        sources[src.id] = src
    for src in sources.values():
        if src.data_via and src.data_via not in sources:
            raise ValueError(f"{src.id}: data_via {src.data_via} is not a listed source")
    return sources


def load_lock(path: Path = LOCK_FILE) -> dict[str, LockEntry]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    return {k: LockEntry.model_validate(v) for k, v in raw.items()}


def save_lock(lock: dict[str, LockEntry], path: Path = LOCK_FILE) -> None:
    body = {k: lock[k].model_dump(mode="json", exclude_none=True) for k in sorted(lock)}
    header = "# Written by `python -m apdt.knowledge.sourcing fetch`. Do not edit by hand.\n"
    path.write_text(header + yaml.safe_dump(body, sort_keys=False, allow_unicode=True),
                    encoding="utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def local_copy(src: Source, sources: dict[str, Source], lock: dict[str, LockEntry]) -> Path:
    """The verified local copy of a source; raises when it is missing or altered."""
    origin = sources[src.data_via] if src.data_via else src
    owner = lock.get(origin.id)
    path = origin.path
    if owner is None or path is None or not path.exists():
        raise FileNotFoundError(f"{src.id} is not fetched")
    if sha256_file(path) != owner.sha256:
        raise ValueError(f"{path.name} does not match its locked hash")
    return path
