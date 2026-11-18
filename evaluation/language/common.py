"""Paths, logging and small helpers shared by the WP14d jobs (laptop and VM)."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ATRA = Path(os.environ["ATRA"]) if "ATRA" in os.environ else None
W = ATRA / "wp14d" if ATRA else None
OUT = (ATRA / "out" / "wp14d") if ATRA else HERE.parents[1] / "var" / "wp14d"
MODELS = (W / "models") if W else HERE.parents[1] / "var" / "wp14d" / "models"
DATA = (W / "data") if W else HERE.parents[1] / "var" / "wp14d" / "data"

LANGS = ("yo", "ha", "ig", "pcm")
NAMES = {"en": "English", "yo": "Yoruba", "ha": "Hausa", "ig": "Igbo", "pcm": "Nigerian Pidgin"}
NLLB = {"en": "eng_Latn", "yo": "yor_Latn", "ha": "hau_Latn", "ig": "ibo_Latn"}


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


def smoke() -> bool:
    """True for a smoke run (`ATRA_SMOKE=1`): a handful of items and steps."""
    return os.environ.get("ATRA_SMOKE") == "1"


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def file_hashes(root: Path, sub: str) -> dict[str, str]:
    """SHA-256 of every file under `root/sub`, keyed by the path relative to `root`."""
    return {f"{sub}/{p.name}": sha256(p) for p in sorted((root / sub).iterdir()) if p.is_file()}
