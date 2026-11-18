"""Importing the APDT models loads no training code and no heavy library."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HEAVY = ["synth", "torchxrayvision", "monai", "d3rlpy", "pymc", "dowhy", "econml",
         "pgmpy", "xgboost", "lightgbm", "torch", "pyshacl", "pm4py", "river"]
ROOT = Path(__file__).resolve().parents[4]


def test_core_modules_import_lightly() -> None:
    code = (
        "import sys, apdt.app, apdt.models.registry, apdt.models.reasoning;"
        "import apdt.models.care.pathways, apdt.models.agency.capacity;"
        f"print([m for m in {HEAVY!r} if m in sys.modules])")
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                         check=True)
    assert out.stdout.strip().splitlines()[-1] == "[]"
