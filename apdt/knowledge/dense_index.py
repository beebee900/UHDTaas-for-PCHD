"""Build the dense guideline index: BGE-small embeddings of every retrieval passage.

    python -m apdt.knowledge.dense_index [--shard 512] [--batch 32]

The passages and the embedder are those of `GuidelineIndex` (`retrieval.py`). The job
embeds them in shards of `--shard` passages under `var/kb_index/shards/<key>/`, so a
restarted run goes on from the last finished shard. At the end it writes the two cache
files that `GuidelineIndex.embeddings()` reads (`<key>.npy` and `<key>.ids.json`), with
the key from the section trees' hashes. Run it where `var/kb_sections` holds the trees.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

from apdt.knowledge.retrieval import EMBED_MODEL, INDEX_DIR, Embedder, GuidelineIndex

SMOKE_SHARDS = 2


def _log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


def build(index: GuidelineIndex, *, shard: int = 512, batch: int = 32,
          max_shards: int | None = None, work_root: Path | None = None) -> Path | None:
    """Embed all passages shard by shard; return the cache `.npy` (None if stopped early)."""
    if index.embedder is None:
        raise RuntimeError("no embedder configured")
    npy, ids_path = index._cache_paths()
    uids = [u.uid for u in index.passages]
    if npy.exists() and ids_path.exists() and json.loads(ids_path.read_text()) == uids:
        _log(f"dense index {npy.name} is current ({len(uids)} passages)")
        return npy
    work = (work_root or INDEX_DIR / "shards") / npy.stem
    work.mkdir(parents=True, exist_ok=True)
    manifest = work / "ids.json"
    plan = {"model": EMBED_MODEL, "shard": shard, "ids": uids}
    if manifest.exists() and json.loads(manifest.read_text()) != plan:
        for old in work.glob("*.npy"):
            old.unlink()
    manifest.write_text(json.dumps(plan))
    texts = [u.text for u in index.passages]
    starts = list(range(0, len(texts), shard))
    dim = index.embedder.dim
    t0, done = time.monotonic(), 0
    for k, start in enumerate(starts):
        if max_shards is not None and k >= max_shards:
            _log(f"stopped after {max_shards} shards")
            return None
        path = work / f"{k:05d}.npy"
        if path.exists():
            continue
        emb = index.embedder.passages(texts[start:start + shard], batch_size=batch)
        if emb.shape != (len(texts[start:start + shard]), dim):
            raise RuntimeError(f"shard {k}: shape {emb.shape}, expected dimension {dim}")
        tmp = work / f"{k:05d}.tmp.npy"
        np.save(tmp, emb)
        tmp.replace(path)
        done += len(emb)
        rate = done / (time.monotonic() - t0)
        left = sum(len(texts[s:s + shard]) for j, s in enumerate(starts)
                   if not (work / f"{j:05d}.npy").exists())
        _log(f"shard {k + 1}/{len(starts)}: {rate:.2f} passages/s, about "
             f"{left / max(rate, 1e-9) / 60:.0f} min left")
    emb = np.concatenate([np.load(work / f"{k:05d}.npy") for k in range(len(starts))])
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    tmp = npy.with_name(npy.stem + ".tmp.npy")
    np.save(tmp, emb.astype(np.float32))
    tmp.replace(npy)
    ids_path.write_text(json.dumps(uids))
    _log(f"wrote {npy} ({emb.shape[0]} x {emb.shape[1]}, {EMBED_MODEL})")
    return npy


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m apdt.knowledge.dense_index")
    parser.add_argument("--shard", type=int, default=512)
    parser.add_argument("--batch", type=int, default=32)
    args = parser.parse_args(argv)
    import torch

    torch.set_num_threads(int(os.environ.get("OMP_NUM_THREADS", "1")))
    index = GuidelineIndex.load(embedder=Embedder())
    _log(f"{len(index.passages)} passages from {len(index.trees)} section trees; "
         f"{EMBED_MODEL}, dimension {index.embedder.dim if index.embedder else '?'}")
    if os.environ.get("ATRA_SMOKE") == "1":
        atra = Path(os.environ.get("ATRA", "/home/ubuntu/atra"))
        build(index, shard=64, batch=args.batch, max_shards=SMOKE_SHARDS,
              work_root=atra / "out-smoke" / "kb_index_shards")
    else:
        build(index, shard=args.shard, batch=args.batch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
