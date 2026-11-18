"""Reference runs of the slow external backends, stored next to the code.

A baseline holds the state and outputs a backend produced for given parameters and inputs.
Instance creation reads it instead of starting the simulator. Each entry carries a
fingerprint of its parameters and inputs; a request with other values runs the backend.
`python -m ahdt.models.external.baselines` regenerates the file with the real backends.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache
from pathlib import Path
from typing import Any

from atra.provenance import record_hash

PATH = Path(__file__).resolve().parent / "baselines.json"
type Entry = dict[str, Any]


@cache
def _all() -> dict[str, Entry]:
    if not PATH.exists():
        return {}
    with PATH.open(encoding="utf-8") as fh:
        data: dict[str, Entry] = json.load(fh)
    return data


def fingerprint(params: Mapping[str, float], inputs: Mapping[str, Any]) -> str:
    return record_hash({"params": dict(params), "inputs": dict(inputs)})[:24]


def lookup(model_id: str, params: Mapping[str, float],
           inputs: Mapping[str, Any]) -> Entry | None:
    entry = _all().get(model_id)
    if entry is not None and entry.get("fingerprint") == fingerprint(params, inputs):
        return entry
    return None


def write(entries: Mapping[str, Entry]) -> None:
    current = dict(_all())
    current.update(entries)
    PATH.write_text(json.dumps(current, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    _all.cache_clear()



def main() -> None:
    import argparse

    from ahdt.models.catalogue import build_catalogue

    parser = argparse.ArgumentParser(description="Regenerate baselines.json with the real backends")
    parser.add_argument("only", nargs="*", help="model ids; all models with a baseline if empty")
    args = parser.parse_args()
    entries: dict[str, Entry] = {}
    for model_id, model in build_catalogue().items():
        if hasattr(model, "baseline") and (not args.only or model_id in args.only):
            entries[model_id] = model.baseline()
            print(model_id, entries[model_id]["backend"], flush=True)
    write(entries)


if __name__ == "__main__":
    main()
