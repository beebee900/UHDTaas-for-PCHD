"""Hidden Markov models in NumPy: clinical health state and mental-health trajectory.

Both are fitted by supervised maximum likelihood on synthetic sequences whose true states
are known (transition and emission counts with add-one smoothing), then run with the
scaled forward-backward recursions:

- the clinical-state HMM has independent categorical emissions per channel (NEWS2 band,
  problem-list count band, number of abnormal vital signs);
- the mental-health HMM has diagonal Gaussian emissions on the PHQ-9 and GAD-7 totals and
  forecasts the next PHQ-9 total with a split-conformal interval.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

type F = NDArray[np.float64]


def forward_backward(log_start: F, log_trans: F, log_emit: F) -> tuple[F, F, float]:
    """Filtered and smoothed state posteriors (T, K) and the sequence log-likelihood.

    `log_emit[t, k]` is log p(observation t | state k).
    """
    t_len, k = log_emit.shape
    trans = np.exp(log_trans)
    emit = np.exp(log_emit - log_emit.max(axis=1, keepdims=True))
    offset = log_emit.max(axis=1)
    alpha = np.empty((t_len, k))
    scale = np.empty(t_len)
    a = np.exp(log_start) * emit[0]
    scale[0] = a.sum()
    alpha[0] = a / scale[0]
    for t in range(1, t_len):
        a = (alpha[t - 1] @ trans) * emit[t]
        scale[t] = a.sum()
        alpha[t] = a / scale[t]
    beta = np.ones((t_len, k))
    for t in range(t_len - 2, -1, -1):
        beta[t] = trans @ (emit[t + 1] * beta[t + 1]) / scale[t + 1]
    smooth = alpha * beta
    smooth /= smooth.sum(axis=1, keepdims=True)
    return alpha, smooth, float(np.log(scale).sum() + offset.sum())


def _transition_counts(sequences: Sequence[Sequence[int]], k: int) -> tuple[F, F]:
    start = np.ones(k)
    trans = np.ones((k, k))
    for z in sequences:
        start[z[0]] += 1
        for a, b in pairwise(z):
            trans[a, b] += 1
    return np.log(start / start.sum()), np.log(trans / trans.sum(axis=1, keepdims=True))


@dataclass
class CategoricalHmm:
    states: list[str]
    channels: list[str]
    levels: list[int]
    log_start: F
    log_trans: F
    log_emit: list[F]
    """Per channel (K, levels)."""

    @classmethod
    def fit(cls, states: Sequence[str], channels: Sequence[str], levels: Sequence[int],
            z: Sequence[Sequence[int]], obs: Sequence[NDArray[np.int64]]) -> CategoricalHmm:
        k = len(states)
        log_start, log_trans = _transition_counts(z, k)
        emits = []
        for c, n in enumerate(levels):
            counts = np.ones((k, n))
            for zz, oo in zip(z, obs, strict=True):
                np.add.at(counts, (np.asarray(zz), oo[:, c]), 1)
            emits.append(np.log(counts / counts.sum(axis=1, keepdims=True)))
        return cls(list(states), list(channels), list(levels), log_start, log_trans, emits)

    def log_emission(self, obs: NDArray[np.int64]) -> F:
        out = np.zeros((len(obs), len(self.states)))
        for c, table in enumerate(self.log_emit):
            out += table[:, np.clip(obs[:, c], 0, self.levels[c] - 1)].T
        return out

    def posteriors(self, obs: NDArray[np.int64]) -> tuple[F, F]:
        alpha, smooth, _ = forward_backward(self.log_start, self.log_trans,
                                            self.log_emission(obs))
        return alpha, smooth

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "categorical", "states": self.states, "channels": self.channels,
                "levels": self.levels, "log_start": self.log_start.tolist(),
                "log_trans": self.log_trans.tolist(),
                "log_emit": [e.tolist() for e in self.log_emit]}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> CategoricalHmm:
        return cls(list(d["states"]), list(d["channels"]), list(d["levels"]),
                   np.asarray(d["log_start"]), np.asarray(d["log_trans"]),
                   [np.asarray(e) for e in d["log_emit"]])


@dataclass
class GaussianHmm:
    states: list[str]
    channels: list[str]
    log_start: F
    log_trans: F
    mean: F
    """(K, C)."""
    var: F

    @classmethod
    def fit(cls, states: Sequence[str], channels: Sequence[str], z: Sequence[Sequence[int]],
            obs: Sequence[F]) -> GaussianHmm:
        k = len(states)
        log_start, log_trans = _transition_counts(z, k)
        zz = np.concatenate([np.asarray(s) for s in z])
        xx = np.concatenate(obs)
        mean = np.stack([xx[zz == s].mean(axis=0) for s in range(k)])
        var = np.stack([xx[zz == s].var(axis=0) + 1e-3 for s in range(k)])
        return cls(list(states), list(channels), log_start, log_trans, mean, var)

    def log_emission(self, obs: F) -> F:
        d = obs[:, None, :] - self.mean[None, :, :]
        out: F = -0.5 * (d**2 / self.var[None] + np.log(2 * np.pi * self.var[None])).sum(axis=2)
        return out

    def posteriors(self, obs: F) -> tuple[F, F]:
        alpha, smooth, _ = forward_backward(self.log_start, self.log_trans,
                                            self.log_emission(obs))
        return alpha, smooth

    def next_mean(self, obs: F) -> tuple[F, F]:
        """Predicted state distribution and expected observation at the next step."""
        alpha, _ = self.posteriors(obs)
        nxt = alpha[-1] @ np.exp(self.log_trans)
        expected: F = nxt @ self.mean
        return nxt, expected

    def to_dict(self) -> dict[str, Any]:
        return {"kind": "gaussian", "states": self.states, "channels": self.channels,
                "log_start": self.log_start.tolist(), "log_trans": self.log_trans.tolist(),
                "mean": self.mean.tolist(), "var": self.var.tolist()}

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> GaussianHmm:
        return cls(list(d["states"]), list(d["channels"]), np.asarray(d["log_start"]),
                   np.asarray(d["log_trans"]), np.asarray(d["mean"]), np.asarray(d["var"]))


def save(model: CategoricalHmm | GaussianHmm, path: Path, **extra: Any) -> None:
    path.write_text(json.dumps(model.to_dict() | extra, indent=1), encoding="utf-8")


def load(path: Path) -> tuple[CategoricalHmm | GaussianHmm, dict[str, Any]]:
    d = json.loads(path.read_text(encoding="utf-8"))
    model: CategoricalHmm | GaussianHmm = (CategoricalHmm.from_dict(d) if d["kind"] == "categorical"
                                           else GaussianHmm.from_dict(d))
    return model, d
