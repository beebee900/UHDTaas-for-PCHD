"""T1 model jobs on the laptop.

    python -m ahdt.models.ml list
    python -m ahdt.models.ml register [--root DIR] [--edge-dir DIR] [--no-cards]
    python -m ahdt.models.ml datasets DIR     record the VM dataset checks (<DIR>/<id>/FETCHED)

The laptop models train with `python -m evaluation.models.ahdt.train`. The VM models train in
the queue of `vm/` and arrive with `vm/pull.sh`, which calls `register`.
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ahdt.models.ml.artifacts import LAPTOP_ROOT, read_metrics
from ahdt.models.ml.inventory import ITEMS


def _list(root: Path) -> None:
    for item in ITEMS:
        m = read_metrics(root / item.spec.model_id)
        state = (f"{m['validation']['metric']}={m['validation']['value']:.4g}" if m
                 else "not trained")
        print(f"{item.spec.model_id:58} {item.runs_on:6} {state}")


def record_datasets(directory: Path) -> list[str]:
    """Merge the VM's FETCHED records into evaluation/datasets/datasets.lock.yaml."""
    import json

    import yaml

    from evaluation.datasets.fetch import LOCK

    lock = yaml.safe_load(LOCK.read_text()) if LOCK.exists() else {}
    done = []
    for path in sorted(directory.glob("*/FETCHED")):
        rec = json.loads(path.read_text(encoding="utf-8"))
        lock[rec["id"]] = {"accessed": rec["accessed"], "bytes": int(rec["bytes"]),
                           "sha256": rec["sha256"], "url": rec["url"], "check": rec["check"],
                           "stored": "Oracle VM /home/ubuntu/atra/data/" + rec["id"]}
        done.append(rec["id"])
    LOCK.write_text(yaml.safe_dump(lock, sort_keys=True))
    return done


async def _register(root: Path, edge_dir: Path, cards: bool) -> None:
    from ahdt.models.ml.register import CARDS_DIR, register
    from atra.backends import Backends
    from atra.config import get_settings

    backends = Backends(get_settings(), "ahdt")
    try:
        for s in await register(backends.models, root=root, edge_dir=edge_dir,
                                cards_dir=CARDS_DIR if cards else None):
            print(f"{s.model_id:58} {s.state:18} {s.detail}")
    finally:
        await backends.close()


def main(argv: list[str] | None = None) -> int:
    from ahdt.models.ml.register import EDGE_DIR

    parser = argparse.ArgumentParser(prog="python -m ahdt.models.ml")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list").add_argument("--root", type=Path, default=LAPTOP_ROOT)
    r = sub.add_parser("register")
    r.add_argument("--root", type=Path, default=LAPTOP_ROOT)
    r.add_argument("--edge-dir", type=Path, default=EDGE_DIR)
    r.add_argument("--no-cards", action="store_true")
    sub.add_parser("datasets").add_argument("dir", type=Path)
    args = parser.parse_args(argv)
    if args.cmd == "list":
        _list(args.root)
    elif args.cmd == "datasets":
        print("recorded: " + (", ".join(record_datasets(args.dir)) or "none"))
    else:
        asyncio.run(_register(args.root, args.edge_dir, not args.no_cards))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
