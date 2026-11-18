"""Shrink WESAD on the VM: keep the chest ECG, EDA, temperature and respiration of the
labelled protocol conditions (1 to 4) as float32 `SX.npz`, then delete `SX.pkl`.

    python ahdt/models/ml/vm/wesad_compact.py [WESAD dir]

A pickle is deleted only after its npz has been written, read back and checked. The
subject readmes stay. Resumable: subjects that already have an npz are skipped.
"""

from __future__ import annotations

import os
import pickle
import sys
from pathlib import Path
from typing import Any

import numpy as np

CHANNELS = ("ECG", "EDA", "Temp", "Resp")
KEEP = (1, 2, 3, 4)
FS = 700


def compact(pkl: Path) -> Path:
    out = pkl.with_suffix(".npz")
    with pkl.open("rb") as fh:
        d = pickle.load(fh, encoding="latin1")
    label = np.asarray(d["label"]).astype(np.int8)
    keep = np.isin(label, KEEP)
    chest = d["signal"]["chest"]
    arrays: dict[str, Any] = {c.lower(): np.asarray(chest[c]).reshape(-1)[keep].astype(np.float32)
              for c in CHANNELS}
    # Sample index in the original recording, so windows never span a removed stretch.
    arrays["index"] = np.flatnonzero(keep).astype(np.int64)
    arrays["label"] = label[keep]
    tmp = out.with_name(out.stem + ".tmp.npz")
    np.savez(tmp, fs=np.int32(FS), **arrays)
    back = np.load(tmp)
    if any(back[k].shape != v.shape for k, v in arrays.items()):
        raise RuntimeError(f"{tmp} does not read back")
    tmp.replace(out)
    del d
    pkl.unlink()
    return out


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else
                os.path.join(os.environ.get("ATRA", "/home/ubuntu/atra"), "data/wesad/WESAD"))
    for pkl in sorted(root.glob("S*/S*.pkl")):
        out = compact(pkl)
        print(f"{pkl.parent.name}: {out.stat().st_size / 1e6:.0f} MB", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
