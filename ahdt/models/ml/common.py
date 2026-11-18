"""Helpers shared by every T1 training job: person-level splits and operating points.

Validation is always on held-out persons or records: a person's rows are all in one of
train (60 %), calibration (20 %) or test (20 %), chosen by a hash of the person key, so a
split does not change when the data grows. Only numpy and the standard library are imported.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from typing import Literal

import numpy as np
from numpy.typing import ArrayLike, NDArray

type Split = Literal["train", "cal", "test"]
SHARES = (0.6, 0.2, 0.2)


def split_of(key: str, salt: str = "t1") -> Split:
    u = int.from_bytes(hashlib.sha256(f"{salt}|{key}".encode()).digest()[:8], "big") / 2**64
    if u < SHARES[0]:
        return "train"
    return "cal" if u < SHARES[0] + SHARES[1] else "test"


def split_masks(keys: Iterable[str], salt: str = "t1") -> dict[Split, NDArray[np.bool_]]:
    s = np.asarray([split_of(k, salt) for k in keys])
    return {"train": s == "train", "cal": s == "cal", "test": s == "test"}


def operating_point(y: ArrayLike, p: ArrayLike, *, min_sensitivity: float = 0.9) -> float:
    """Highest threshold whose sensitivity on (y, p) is at least `min_sensitivity`."""
    yy = np.asarray(y, dtype=bool)
    pp = np.asarray(p, dtype=float)
    pos = np.sort(pp[yy])[::-1]
    if pos.size == 0:
        return 0.5
    k = int(np.ceil(min_sensitivity * pos.size)) - 1
    return float(pos[min(max(k, 0), pos.size - 1)])


def sensitivity_specificity(y: ArrayLike, p: ArrayLike, threshold: float) -> tuple[float, float]:
    yy = np.asarray(y, dtype=bool)
    hit = np.asarray(p, dtype=float) >= threshold
    sens = float(hit[yy].mean()) if yy.any() else float("nan")
    spec = float((~hit[~yy]).mean()) if (~yy).any() else float("nan")
    return sens, spec


def age_band(age: float, bands: Iterable[tuple[str, float, float]]) -> str:
    for label, lo, hi in bands:
        if lo <= age < hi:
            return label
    return "unknown"
