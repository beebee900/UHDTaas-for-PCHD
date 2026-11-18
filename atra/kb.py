"""Knowledge-base entries by id (design 06, section 6.3).

Every kb YAML file holds a list of entries. An entry has an `id`, its content and a
`provenance` block (6.3.2). Rules, goals and models refer to entries with
`{"kb": "<id>"}` instead of writing clinical numbers into code (rule R5).
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, model_validator


class Citation(BaseModel):
    """A place in a source. `page` is the 1-based PDF page, not the printed folio."""

    model_config = ConfigDict(extra="forbid")

    source: str
    section: str | None = None
    page: int | None = None


class Provenance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source: str | None = None
    section: str | None = None
    page: int | None = None
    also: list[Citation] = []
    derived: dict[str, str] = {}
    extracted_by: Literal["llm", "human"] | None = None
    verified_by: str | None = None
    status: Literal["draft", "verified", "approved"] = "draft"
    assumption: bool = False
    justification: str | None = None

    def citations(self) -> list[Citation]:
        """The primary citation followed by the additional ones."""
        first = ([Citation(source=self.source, section=self.section, page=self.page)]
                 if self.source else [])
        return first + list(self.also)

    @model_validator(mode="after")
    def _justified(self) -> Provenance:
        if self.assumption and not self.justification:
            raise ValueError("an assumption needs a justification")
        return self


class Entry(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    provenance: Provenance

    def content(self) -> dict[str, Any]:
        return {k: v for k, v in self.model_dump().items() if k not in {"id", "provenance"}}


class KBError(KeyError):
    pass


NOT_ENTRY_FILES = frozenset({"sources.yaml", "sources.lock.yaml"})


_PATH_STEP = re.compile(r"\[[^\]]+\]|[^.\[\]]+")


class KnowledgeBase:
    """All entries under one kb directory, indexed by id."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self._entries: dict[str, tuple[Path, Entry]] = {}
        self._lock = threading.Lock()
        self.reload()

    def reload(self) -> None:
        entries: dict[str, tuple[Path, Entry]] = {}
        for path in sorted(self.directory.rglob("*.yaml")):
            if path.name in NOT_ENTRY_FILES:
                continue
            with path.open(encoding="utf-8") as fh:
                data = yaml.safe_load(fh)
            if not isinstance(data, list):
                continue
            for raw in data:
                if not isinstance(raw, Mapping) or "id" not in raw:
                    continue
                entry = Entry.model_validate(raw)
                if entry.id in entries:
                    raise ValueError(f"kb id {entry.id} is defined twice "
                                     f"({entries[entry.id][0].name}, {path.name})")
                entries[entry.id] = (path, entry)
        with self._lock:
            self._entries = entries

    def __contains__(self, entry_id: object) -> bool:
        return entry_id in self._entries

    def entry(self, entry_id: str) -> Entry:
        try:
            return self._entries[entry_id][1]
        except KeyError:
            raise KBError(entry_id) from None

    def resolve(self, entry_id: str) -> Any:
        """The entry's `value` when it has one, else its whole content."""
        content = self.entry(entry_id).content()
        return content.get("value", content)

    def lookup(self, entry_id: str, path: str) -> Any:
        """The value at `path` in the entry's content.

        `path` is dotted keys with list steps `[2]` (index) or `[key=value]` (the item
        whose `key` equals `value`), for example `bands[band=high].min_total`.
        """
        obj: Any = self.entry(entry_id).content()
        for step in _PATH_STEP.findall(path):
            try:
                if step.startswith("[") and "=" in step:
                    key, want = step[1:-1].split("=", 1)
                    obj = next(i for i in obj if str(i.get(key)) == want)
                elif step.startswith("["):
                    obj = obj[int(step[1:-1])]
                else:
                    obj = obj[step]
            except (KeyError, IndexError, StopIteration, TypeError, AttributeError):
                raise KBError(f"{entry_id}: {path}") from None
        return obj

    def resolve_refs(self, obj: Any) -> Any:
        """A copy of `obj` with every `{"kb": id}` replaced by the resolved entry."""
        if isinstance(obj, Mapping):
            if set(obj) == {"kb"}:
                return self.resolve(str(obj["kb"]))
            return {k: self.resolve_refs(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.resolve_refs(v) for v in obj]
        return obj

    def drafts(self) -> Iterator[str]:
        return (eid for eid, (_, e) in self._entries.items() if e.provenance.status == "draft")

    def ids(self) -> list[str]:
        return sorted(self._entries)

    def path_of(self, entry_id: str) -> Path:
        try:
            return self._entries[entry_id][0]
        except KeyError:
            raise KBError(entry_id) from None
