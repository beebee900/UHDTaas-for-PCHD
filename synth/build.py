"""Build the synthetic population (design 08, WP02).

    python -m synth.build --persons 1000 [--seed 7] [--out var/synth] [--personas]

Writes, under `<out>/<seed>/`:
- persons.jsonl, network.jsonl, episodes.jsonl: who exists and what happens to them
- observations.jsonl (device readings), labs.jsonl, findings.jsonl, notes.jsonl: what the
  services see, with measurement error
- cohort.parquet and trajectories.parquet: causal and offline RL data
- truth/: the truth physiology and the cohort's true effects, read only by `evaluation/`

`--personas` also regenerates `synth/personas/<key>.json`. Records are written person by
person, so memory does not grow with the population.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from collections import defaultdict
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq

from ahdt.models.catalogue import default_catalogue
from atra.config import ROOT
from synth.cohort import therapy_trajectories, treatment_cohort
from synth.conditions import assign_chronic, episodes
from synth.personas import write_personas
from synth.population import generate
from synth.records import device_readings, findings, labs, note
from synth.truth import person_truth

START = "2026-01-01T00:00:00+00:00"


def _line(fh: Any, obj: Any) -> None:
    fh.write(json.dumps(obj, sort_keys=True, ensure_ascii=False) + "\n")


async def build(persons: int, seed: int, out: Path, *, personas: bool = False
                ) -> dict[str, Any]:
    from datetime import datetime

    t0 = time.monotonic()
    base = out / str(seed)
    truth_dir = base / "truth"
    truth_dir.mkdir(parents=True, exist_ok=True)
    people, graph = generate(persons, seed)
    assign_chronic(people, seed)
    eps = episodes(people, seed)
    by_person = defaultdict(list)
    for e in eps:
        by_person[e.hdt_id].append(e)
    models = default_catalogue()
    start = datetime.fromisoformat(START)
    counts: dict[str, int] = defaultdict(int)
    files = {name: (base / f"{name}.jsonl").open("w", encoding="utf-8") for name in
             ("persons", "episodes", "observations", "labs", "findings", "notes")}
    truth_file = (truth_dir / "persons.jsonl").open("w", encoding="utf-8")
    try:
        for p in people:
            mine = by_person.get(p.hdt_id, [])
            truth = await person_truth(p, models, mine)
            _line(truth_file, truth.record())
            _line(files["persons"], p.record())
            for e in mine:
                _line(files["episodes"], e.record())
                found = findings(p, [e.condition], e.episode_key, e.severity)
                _line(files["findings"], {"hdt_id": p.hdt_id, "episode": e.episode_key,
                                          "findings": found})
                _line(files["notes"], note(p, e.condition, found, e.onset))
                counts["notes"] += 1
            for obs in device_readings(p, truth, mine, start):
                _line(files["observations"], obs)
                counts["observations"] += 1
            for lab in labs(p, truth, mine, start):
                _line(files["labs"], lab)
                counts["labs"] += 1
    finally:
        for fh in files.values():
            fh.close()
        truth_file.close()
    with (base / "network.jsonl").open("w", encoding="utf-8") as fh:
        for a, b, data in sorted(graph.edges(data=True)):
            _line(fh, {"a": a, "b": b, "kind": data["kind"]})
    observed, effects = treatment_cohort(seed)
    pq.write_table(observed, base / "cohort.parquet")
    pq.write_table(effects, truth_dir / "cohort_effects.parquet")
    pq.write_table(await therapy_trajectories(models, seed), base / "trajectories.parquet")
    if personas:
        await write_personas(models, truth_dir=truth_dir)
    manifest = {"seed": seed, "persons": len(people), "episodes": len(eps),
                "edges": graph.number_of_edges(), **counts,
                "conditions": {c: sum(c in p.conditions for p in people)
                               for c in sorted({c for p in people for c in p.conditions})},
                "seconds": round(time.monotonic() - t0, 1)}
    (base / "manifest.json").write_text(json.dumps(manifest, indent=1, sort_keys=True))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m synth.build")
    parser.add_argument("--persons", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--out", type=Path, default=ROOT / "var" / "synth")
    parser.add_argument("--personas", action="store_true")
    args = parser.parse_args(argv)
    manifest = asyncio.run(build(args.persons, args.seed, args.out, personas=args.personas))
    print(json.dumps(manifest, indent=1, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
