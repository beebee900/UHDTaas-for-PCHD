"""Command line of the language models.

    python -m ahdt.models.language register --src DIR [--dest DIR] [--no-cards]
    python -m ahdt.models.language list [--root DIR]
"""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from ahdt.models.language.slm import MODELS_DIR, adapter_dir
from atra.config import ROOT

DEFAULT_SRC = ROOT / "var" / "wp14d" / "pulled"


async def _register(src: Path, dest: Path, cards: bool) -> None:
    from ahdt.models.language.register import CARDS_DIR, register
    from atra.backends import Backends
    from atra.config import get_settings

    backends = Backends(get_settings(), "ahdt")
    try:
        for s in await register(backends.models, src=src, dest=dest,
                                cards_dir=CARDS_DIR if cards else None):
            print(f"{s.model_id:34} {s.state:18} {s.detail}")
    finally:
        await backends.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m ahdt.models.language")
    sub = parser.add_subparsers(dest="cmd", required=True)
    reg = sub.add_parser("register")
    reg.add_argument("--src", type=Path, default=DEFAULT_SRC)
    reg.add_argument("--dest", type=Path, default=MODELS_DIR)
    reg.add_argument("--no-cards", action="store_true")
    ls = sub.add_parser("list")
    ls.add_argument("--root", type=Path, default=MODELS_DIR)
    args = parser.parse_args(argv)
    if args.cmd == "register":
        asyncio.run(_register(args.src, args.dest, not args.no_cards))
        return 0
    for code in ("yo", "ha", "ig", "pcm"):
        path = adapter_dir(code, args.root)
        print(f"lora-{code:4} {'installed: ' + str(path) if path else 'not installed'}")
    voice = args.root / "mms-tts-ibo-ft" / "config.json"
    print(f"mms-tts-ibo-ft {'installed' if voice.is_file() else 'not installed'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
