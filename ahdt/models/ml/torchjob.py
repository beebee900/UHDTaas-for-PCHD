"""Shared parts of the torch training jobs on the VM (ECG, sleep): thread limit, small 1D-CNN
blocks, a resumable training loop with per-epoch checkpoints, and batched prediction.

The loop keeps the weights of the epoch with the best validation score and stops after
`patience` epochs without improvement. Its checkpoint holds the model, the optimiser, the
epoch, the best weights and the history, so a restarted job goes on from the last epoch.
"""

from __future__ import annotations

import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import torch
from numpy.typing import NDArray
from sklearn.metrics import f1_score
from torch import nn

Arrays = Sequence[NDArray[Any]]


def setup(seed: int = 0) -> None:
    """One thread (the VM unit has a quota of one core) and fixed seeds."""
    torch.set_num_threads(1)
    torch.manual_seed(seed)
    np.random.seed(seed)


def log(msg: str) -> None:
    print(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}", file=sys.stderr, flush=True)


def smoke() -> bool:
    """True when the job runs as a smoke test (`ATRA_SMOKE=1`): a few records, one epoch."""
    return os.environ.get("ATRA_SMOKE") == "1"


def save_atomic(obj: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    torch.save(obj, tmp)
    tmp.replace(path)


def block(cin: int, cout: int, k: int, stride: int) -> nn.Sequential:
    return nn.Sequential(nn.Conv1d(cin, cout, k, stride, padding=k // 2, bias=False),
                         nn.BatchNorm1d(cout), nn.ReLU())


class Standardize(nn.Module):
    """Zero mean and unit variance per input strip, so the edge can feed raw millivolts."""

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        mean = x.mean(dim=-1, keepdim=True)
        std = x.std(dim=-1, keepdim=True)
        return (x - mean) / (std + 1e-3)


class GlobalPool(nn.Module):
    """Concatenated global average and max pooling over time."""

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return torch.cat([x.mean(dim=-1), x.amax(dim=-1)], dim=1)


def class_weights(y: NDArray[Any], k: int, power: float = 0.5) -> torch.Tensor:
    """Class frequency to the power `-power`, mean 1 over the present classes."""
    counts = np.bincount(y, minlength=k).astype(float)
    w = np.where(counts > 0, np.maximum(counts, 1.0) ** -power, 0.0)
    w = w / w[counts > 0].mean()
    return torch.tensor(w, dtype=torch.float32)


def _batch(arrays: Arrays, idx: NDArray[np.int64]) -> list[torch.Tensor]:
    return [torch.from_numpy(np.asarray(a[idx], dtype=np.float32)) for a in arrays]


def predict_proba(model: nn.Module, arrays: Arrays, batch: int = 256) -> NDArray[np.float64]:
    model.eval()
    n = len(arrays[0])
    out = []
    with torch.no_grad():
        for start in range(0, n, batch):
            idx = np.arange(start, min(start + batch, n))
            out.append(torch.softmax(model(*_batch(arrays, idx)), dim=1).numpy())
    return np.concatenate(out).astype(float) if out else np.zeros((0, 0))


def macro_f1(y: NDArray[Any], proba: NDArray[np.float64], labels: Sequence[int]) -> float:
    return float(f1_score(y, proba.argmax(axis=1), labels=list(labels), average="macro",
                          zero_division=0))


@dataclass
class Fit:
    epochs: int = 20
    batch: int = 128
    lr: float = 1e-3
    weight_decay: float = 1e-4
    patience: int = 4
    seed: int = 0
    score_labels: Sequence[int] = ()
    history: list[dict[str, float]] = field(default_factory=list)


def fit(model: nn.Module, train: Arrays, y_train: NDArray[Any], val: Arrays,
        y_val: NDArray[Any], cfg: Fit, ckpt: Path, *,
        weights: torch.Tensor | None = None,
        sampler: Callable[[np.random.Generator], NDArray[np.int64]] | None = None) -> Fit:
    """Train with Adam and cross-entropy; resume from `ckpt`; load the best weights at the end.

    `sampler` returns the training indices of one epoch (default: a permutation of all rows).
    """
    opt = torch.optim.Adam(model.parameters(), lr=cfg.lr, weight_decay=cfg.weight_decay)
    loss_fn = nn.CrossEntropyLoss(weight=weights)
    start, best, best_state, stale = 0, -1.0, None, 0
    if ckpt.exists():
        state = torch.load(ckpt, weights_only=False)
        model.load_state_dict(state["model"])
        opt.load_state_dict(state["opt"])
        start, best, best_state = state["epoch"], state["best"], state["best_state"]
        stale, cfg.history = state["stale"], state["history"]
        log(f"resume {ckpt.parent.name}/{ckpt.name} at epoch {start}, best {best:.4f}")
    labels = cfg.score_labels or range(int(max(y_train.max(), y_val.max())) + 1)
    yt = torch.from_numpy(np.asarray(y_train, dtype=np.int64))
    for epoch in range(start, cfg.epochs):
        if stale >= cfg.patience:
            break
        rng = np.random.default_rng(cfg.seed * 1000 + epoch)
        order = sampler(rng) if sampler else rng.permutation(len(y_train))
        model.train()
        t0, total, seen = time.monotonic(), 0.0, 0
        for b in range(0, len(order), cfg.batch):
            idx = np.sort(order[b:b + cfg.batch])
            if len(idx) < 2:
                continue
            opt.zero_grad()
            loss = loss_fn(model(*_batch(train, idx)), yt[idx])
            loss.backward()
            opt.step()
            total += float(loss) * len(idx)
            seen += len(idx)
        score = macro_f1(y_val, predict_proba(model, val), labels)
        cfg.history.append({"epoch": epoch + 1, "loss": total / max(seen, 1),
                            "val_macro_f1": score, "seconds": time.monotonic() - t0})
        if score > best:
            best, stale = score, 0
            best_state = {k: v.clone() for k, v in model.state_dict().items()}
        else:
            stale += 1
        log(f"{ckpt.parent.parent.name} {ckpt.stem} epoch {epoch + 1}/{cfg.epochs} loss "
            f"{total / max(seen, 1):.4f} val macro-F1 {score:.4f} "
            f"({time.monotonic() - t0:.0f} s)")
        save_atomic({"model": model.state_dict(), "opt": opt.state_dict(), "epoch": epoch + 1,
                     "best": best, "best_state": best_state, "stale": stale,
                     "history": cfg.history}, ckpt)
    if best_state is not None:
        model.load_state_dict(best_state)
    return cfg


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=1, default=float), encoding="utf-8")
