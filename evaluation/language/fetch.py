"""Download the WP14d models and corpora on the VM and record size and SHA-256 per file.

    python -m evaluation.language.fetch [keys...]       (default: every entry)

Files go to `$ATRA/wp14d/models/<key>` and `$ATRA/wp14d/data/`. The manifest
`$ATRA/out/wp14d/downloads.json` lists URL, licence, bytes and SHA-256 for each file. A file
that is already present with the right size is kept.
"""

from __future__ import annotations

import fnmatch
import hashlib
import json
import os
import shutil
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any

from evaluation.language.sources import (
    FINETUNE_HF_VITS_URL,
    MAFAND_PAIRS,
    MAFAND_URL,
    MENYO_URL,
    MODELS,
    HFModel,
)

ATRA = Path(os.environ.get("ATRA", "/home/ubuntu/atra"))
W = ATRA / "wp14d"
MIN_FREE_GB = 8


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def free_gb() -> float:
    return shutil.disk_usage(W).free / 1e9


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


def http_get(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "atra-health-wp14d/0.1"})
    with urllib.request.urlopen(req, timeout=300) as r, target.open("wb") as fh:
        shutil.copyfileobj(r, fh, 1 << 20)


def fetch_hf(entry: HFModel, manifest: dict[str, dict[str, Any]]) -> None:
    from huggingface_hub import HfApi, hf_hub_download

    api = HfApi()
    info = api.repo_info(entry.repo, repo_type=entry.kind, files_metadata=True)
    sizes = {s.rfilename: s.size or 0 for s in getattr(info, "siblings", None) or []}
    names = list(entry.files) or [n for n in sizes if not any(
        fnmatch.fnmatch(n, p) for p in entry.skip)]
    local = W / "models" / entry.key if entry.kind == "model" else W / "data" / entry.key
    need = sum(sizes[n] for n in names) / 1e9
    if free_gb() - need < MIN_FREE_GB:
        raise SystemExit(f"{entry.key}: {need:.1f} GB needed, {free_gb():.1f} GB free")
    for name in names:
        path = local / name
        if not path.exists() or path.stat().st_size != sizes[name]:
            log(f"{entry.key}: {name} ({sizes[name] / 1e6:.0f} MB)")
            hf_hub_download(entry.repo, name, repo_type=entry.kind, local_dir=local)
        manifest[f"{entry.key}/{name}"] = {
            "url": f"https://huggingface.co/{entry.repo}", "revision": info.sha,
            "licence": entry.licence, "bytes": path.stat().st_size, "sha256": sha256(path)}


def fetch_plain(key: str, url: str, target: Path, licence: str,
                manifest: dict[str, dict[str, Any]]) -> None:
    if not target.exists():
        log(f"{key}: {url}")
        http_get(url, target)
    manifest[key] = {"url": url, "licence": licence, "bytes": target.stat().st_size,
                     "sha256": sha256(target)}


def main(argv: list[str]) -> int:
    W.mkdir(parents=True, exist_ok=True)
    out = ATRA / "out" / "wp14d" / "downloads.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, dict[str, Any]] = json.loads(out.read_text()) if out.exists() else {}
    wanted = set(argv)
    for entry in MODELS:
        if not wanted or entry.key in wanted:
            fetch_hf(entry, manifest)
            out.write_text(json.dumps(manifest, indent=1))
    if not wanted or "corpora" in wanted:
        for pair in MAFAND_PAIRS:
            for split in ("train", "dev", "test"):
                fetch_plain(f"mafand/{pair}/{split}", f"{MAFAND_URL}/{pair}/{split}.json",
                            W / "data" / "mafand" / pair / f"{split}.json", "CC-BY-NC-4.0",
                            manifest)
        fetch_plain("menyo-20k", MENYO_URL, W / "data" / "menyo-20k.zip", "CC-BY-NC-4.0",
                    manifest)
        fetch_plain("finetune-hf-vits", FINETUNE_HF_VITS_URL,
                    W / "data" / "finetune-hf-vits.zip", "MIT", manifest)
        out.write_text(json.dumps(manifest, indent=1))
    log(f"free disk {free_gb():.1f} GB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
