"""A decision tree distilled from the value-of-information policy, for the CHW app offline.

The tree maps what is known (age, sex and the findings and results asked so far) to the next
test the policy would order. It is trained by `evaluation.models.apdt.distill`, stored as
JSON, and evaluated here without scikit-learn so it can run in the app.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from apdt.models.context import Observations, Patient
from apdt.models.diagnosis.comparator import APDT_ROOT, features

MODEL_ID = "apdt.diagnosis.test_policy_tree"
FILE = "tree.json"


def encode(patient: Patient, obs: Observations) -> NDArray[np.float64]:
    """Feature row with 1 present, 0 absent and -1 not asked."""
    row: NDArray[np.float64] = np.nan_to_num(features(patient, obs), nan=-1.0)
    return row


@dataclass(frozen=True)
class PolicyTree:
    spec: dict[str, Any]

    @classmethod
    def load(cls, root: Path | None = None) -> PolicyTree | None:
        path = (root or APDT_ROOT) / MODEL_ID / FILE
        return cls(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else None

    def next_test(self, patient: Patient, obs: Observations) -> str:
        row = encode(patient, obs)
        t = self.spec["tree"]
        node = 0
        while t["left"][node] != -1:
            go_left = row[t["feature"][node]] <= t["threshold"][node]
            node = t["left"][node] if go_left else t["right"][node]
        return str(self.spec["classes"][t["value"][node]])

    def rules(self) -> list[str]:
        """The tree as readable if-then lines."""
        t, names = self.spec["tree"], self.spec["features"]
        lines: list[str] = []

        def walk(node: int, prefix: str) -> None:
            if t["left"][node] == -1:
                lines.append(f"{prefix}order {self.spec['classes'][t['value'][node]]}")
                return
            name, thr = names[t["feature"][node]], t["threshold"][node]
            walk(t["left"][node], f"{prefix}if {name} <= {thr:.2f}: ")
            walk(t["right"][node], f"{prefix}if {name} > {thr:.2f}: ")

        walk(0, "")
        return lines
