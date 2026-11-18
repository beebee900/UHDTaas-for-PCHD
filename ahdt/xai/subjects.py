"""Subjects: a model, the instance to explain and the data an explainer needs.

One class per kind of model (see `KINDS`). The loaders build a subject from a trained T1
artifact directory, so every explainer runs against the model that serves.

No subject reads the synthetic truth. When a caller has no reference population, an
explainer uses `reference_set`, a local sample around the instance.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from ahdt.xai.types import Array

type Scorer = Callable[[Array], Array]


def reference_set(x: Array, n: int = 40, rel: float = 0.25, seed: int = 0,
                  lo: Array | None = None, hi: Array | None = None) -> Array:
    """`n` rows sampled around the instance: each value scaled by a factor in 1 +/- `rel`,
    plus a small absolute spread for values at zero. Used when no population is supplied."""
    rng = np.random.default_rng(seed)
    scale = np.maximum(np.abs(x), 1.0) * rel
    rows = x + rng.uniform(-1.0, 1.0, size=(n, len(x))) * scale
    if lo is not None:
        rows = np.maximum(rows, lo)
    if hi is not None:
        rows = np.minimum(rows, hi)
    return np.asarray(rows, dtype=float)


@dataclass
class TabularSubject:
    """A model that scores feature rows: LightGBM risk models and the Cox model."""

    model_id: str
    version: str
    features: list[str]
    x: Array
    background: Array
    predict: Scorer
    label: str = "risk"
    booster: Any | None = None
    actionable: frozenset[str] = frozenset()
    bounds: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    threshold: float = 0.5
    conformal: float | None = None
    level: float = 0.9
    kind: str = "tabular"

    @property
    def output(self) -> float:
        return float(self.predict(self.x[None, :])[0])

    def row(self, x: Array | None = None) -> dict[str, float]:
        v = self.x if x is None else x
        return {f: float(a) for f, a in zip(self.features, v, strict=True)}


@dataclass
class WindowSubject:
    """A forecaster over a window of past values; the scalar output is the mean forecast of
    one column over the horizon."""

    model_id: str
    version: str
    columns: list[str]
    history: Array
    predict_batch: Callable[[Sequence[Array]], Array]
    horizon: int
    target: int = 0
    block: int = 7
    halfwidth: Array | None = None
    level: float = 0.9
    kind: str = "forecast"

    def forecast(self, window: Array) -> Array:
        out: Array = self.predict_batch([window])[0]
        return out

    def score(self, windows: Sequence[Array]) -> Array:
        out = self.predict_batch(windows)
        return np.asarray(out[:, :, self.target].mean(axis=1), dtype=float)

    @property
    def output(self) -> float:
        return float(self.score([self.history])[0])


@dataclass
class SequenceSubject:
    """A hidden Markov model scoring an observation sequence; the output is the filtered
    probability of `target` at the last step."""

    model_id: str
    version: str
    channels: list[str]
    obs: Array
    posterior: Callable[[Any], Array]
    states: list[str]
    target: str
    halfwidth: float | None = None
    level: float = 0.9
    kind: str = "sequence"

    @property
    def output(self) -> float:
        return float(self.posterior(self.obs)[self.states.index(self.target)])


@dataclass
class OnlineSubject:
    """A per-person online baseline; the output is the largest field z-score."""

    model_id: str
    version: str
    fields: list[str]
    x: Mapping[str, float]
    score: Callable[[Mapping[str, float]], Mapping[str, float]]
    threshold: float
    kind: str = "online"

    @property
    def output(self) -> float:
        return float(max(self.score(self.x).values()))


@dataclass
class SignalSubject:
    """A torch network on a waveform; the output is the probability of class `target`."""

    model_id: str
    version: str
    net: Any
    x: Array
    classes: list[str]
    target: int
    fs: float
    conformal: float | None = None
    level: float = 0.9
    kind: str = "signal"

    def proba(self, batch: Array) -> Array:
        import torch

        with torch.no_grad():
            logits = self.net(torch.as_tensor(batch, dtype=torch.float32))
            return np.asarray(logits.numpy(), dtype=float)

    @property
    def output(self) -> float:
        return float(self.proba(self.x[None, :])[0, self.target])


@dataclass
class GraphSubject:
    """A node-level GNN on a person's network."""

    model_id: str
    version: str
    net: Any
    x: Any
    edge_index: Any
    node: int
    features: list[str]
    kind: str = "graph"

    @property
    def output(self) -> float:
        import torch

        with torch.no_grad():
            return float(torch.sigmoid(self.net(self.x, self.edge_index))[self.node])


@dataclass
class MechanisticSubject:
    """A T2 simulation or algebraic model: parameters, inputs and one output of interest."""

    model: Any
    inputs: Mapping[str, Any]
    output_name: str
    horizon_s: float = 0.0
    params: Mapping[str, float] = field(default_factory=dict)
    state: Mapping[str, Any] = field(default_factory=dict)
    posterior_std: Mapping[str, float] = field(default_factory=dict)
    kind: str = "mechanistic"

    @property
    def model_id(self) -> str:
        return str(self.model.model_id)

    @property
    def version(self) -> str:
        return str(self.model.version)


@dataclass
class RuleSubject:
    """A rule-based model: the inputs and the outputs the rules produced."""

    model: Any
    inputs: Mapping[str, Any]
    kind: str = "rules"

    @property
    def model_id(self) -> str:
        return str(self.model.model_id)

    @property
    def version(self) -> str:
        return str(self.model.version)


@dataclass
class ReferenceSubject:
    """A T3 reference-state model and its current state."""

    model: Any
    state: Mapping[str, Any]
    inputs: Mapping[str, Any] = field(default_factory=dict)
    kind: str = "reference"

    @property
    def model_id(self) -> str:
        return str(self.model.model_id)

    @property
    def version(self) -> str:
        return str(self.model.version)


@dataclass
class TextSubject:
    """An SLM or LLM answer with the sources it was given.

    `sample` draws one more answer to the same prompt (self-consistency).
    """

    model_id: str
    version: str
    question: str
    answer: str
    sources: Mapping[str, str]
    sample: Callable[[], str] | None = None
    kind: str = "text"


def _read(directory: Path, name: str = "model.json") -> dict[str, Any]:
    data: dict[str, Any] = json.loads((directory / name).read_text(encoding="utf-8"))
    return data


def version_of(directory: Path) -> str:
    metrics = directory / "metrics.json"
    if metrics.exists():
        return str(json.loads(metrics.read_text(encoding="utf-8")).get("version", "1.0.0"))
    return "1.0.0"


def tabular_subject(model_id: str, directory: Path, row: Mapping[str, float], *,
                    background: Array | None = None, seed: int = 0,
                    actionable: Sequence[str] = ()) -> TabularSubject:
    """A LightGBM T1 model (`model.txt`) or the Cox adherence model (`model.json`)."""
    from ahdt.models.ml import survival, tabular

    version = version_of(directory)
    if (directory / tabular.MODEL_FILE).exists():
        pred = tabular.Predictor(directory)
        features = pred.features

        def score(rows: Array) -> Array:
            return np.asarray(pred.probability([dict(zip(features, r, strict=True))
                                                for r in rows]), dtype=float)

        booster: Any | None = pred.booster
    else:
        cox = survival.Predictor(directory)
        features = list(cox.p["covariates"])

        def score(rows: Array) -> Array:
            return np.array([cox.gap_probability(dict(zip(features, r, strict=True)))
                             for r in rows], dtype=float)

        booster = None
    x = np.array([float(row[f]) for f in features])
    bg = background if background is not None else reference_set(x, seed=seed)
    meta = _read(directory) if (directory / "model.json").exists() else {}
    return TabularSubject(model_id, version, list(features), x, np.asarray(bg, dtype=float),
                          score, booster=booster,
                          actionable=frozenset(actionable or features),
                          bounds={f: (float(bg[:, i].min()), float(bg[:, i].max()))
                                  for i, f in enumerate(features)},
                          conformal=meta.get("conformal_threshold"),
                          level=float(meta.get("level", 0.9)))


def window_subject(model_id: str, directory: Path, history: Array, *,
                   target: str | None = None) -> WindowSubject:
    from ahdt.models.ml import forecast

    meta = _read(directory)
    pred = forecast.Predictor(directory)
    columns = list(meta["columns"])
    h = int(meta["history"])
    scale = pred.scale

    def batch(windows: Sequence[Array]) -> Array:
        arrays = [np.asarray(w, dtype=np.float32)[-h:] for w in windows]
        return np.asarray(forecast._forecast(pred.model, arrays, scale, int(meta["horizon"])),
                          dtype=float)

    return WindowSubject(model_id, version_of(directory), columns,
                         np.asarray(history, dtype=float)[-h:], batch, int(meta["horizon"]),
                         target=columns.index(target) if target else 0,
                         halfwidth=np.asarray(meta["halfwidth"], dtype=float),
                         level=float(meta["level"]))


def sequence_subject(model_id: str, directory: Path, obs: Array, target: str
                     ) -> SequenceSubject:
    from ahdt.models.ml import hmm

    model, meta = hmm.load(directory / "model.json")

    def posterior(o: Any) -> Array:
        alpha, _ = model.posteriors(o)
        out: Array = alpha[-1]
        return out

    return SequenceSubject(model_id, version_of(directory), list(model.channels),
                           np.asarray(obs), posterior, list(model.states), target,
                           halfwidth=meta.get("phq9_halfwidth_90"))


def online_subject(model_id: str, directory: Path, history: Sequence[Mapping[str, float]],
                   x: Mapping[str, float]) -> OnlineSubject:
    """The baseline is learnt from `history` (one row per past day), then scores `x`."""
    from ahdt.models.ml import online

    meta = _read(directory)
    base = online.Baseline(meta["fields"], float(meta["fading_factor"]))
    for row in history:
        base.learn(row)
    return OnlineSubject(model_id, version_of(directory), list(meta["fields"]), dict(x),
                         base.score, float(meta["threshold_z"]))


def signal_subject(model_id: str, directory: Path, signal: Array, *,
                   target: int | None = None) -> SignalSubject:
    """The PTB-XL rhythm ensemble or the sleep-stage network, as logits-to-probabilities."""
    import torch

    meta = _read(directory)
    state = torch.load(directory / "model.pt", weights_only=True, map_location="cpu")
    if "classes" in meta:
        from ahdt.models.ml import ecg

        net: Any = ecg.Ensemble([ecg.RhythmNet() for _ in range(int(meta["members"]))])
        net.load_state_dict(state)
        classes = list(meta["classes"])
        fs = float(meta["fs"])
    else:
        from ahdt.models.ml import sleep

        inner = sleep.SleepNet()
        inner.load_state_dict(state)

        class Probs(torch.nn.Module):
            def __init__(self, m: torch.nn.Module) -> None:
                super().__init__()
                self.m = m

            def forward(self, x: torch.Tensor) -> torch.Tensor:
                return torch.softmax(self.m(x), dim=1)

        net = Probs(inner)
        classes = list(meta["stages"])
        fs = float(meta["fs"])
    net.eval()
    x = np.asarray(signal, dtype=float)
    chosen = target
    if chosen is None:
        with torch.no_grad():
            chosen = int(net(torch.as_tensor(x[None, :], dtype=torch.float32)).argmax())
    return SignalSubject(model_id, version_of(directory), net, x, classes, chosen, fs,
                         conformal=meta.get("conformal_threshold"),
                         level=float(meta.get("level", 0.9)))


def beat_subject(model_id: str, directory: Path, beat: Array, rr: Array,
                 *, target: int | None = None) -> SignalSubject:
    """The MIT-BIH beat classifier; the RR features are held fixed."""
    import torch

    from ahdt.models.ml import ecg

    net = ecg.BeatNet()
    net.load_state_dict(torch.load(directory / "model.pt", weights_only=True,
                                   map_location="cpu"))
    net.eval()
    rr_t = torch.as_tensor(np.asarray(rr, dtype=float)[None, :], dtype=torch.float32)

    class Fixed(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.beat = net

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return torch.softmax(self.beat(x, rr_t.expand(len(x), -1)), dim=1)

    x = np.asarray(beat, dtype=float)
    fixed = Fixed().eval()
    chosen = target
    if chosen is None:
        with torch.no_grad():
            chosen = int(fixed(torch.as_tensor(x[None, :], dtype=torch.float32)).argmax())
    return SignalSubject(model_id, version_of(directory), fixed, x, list(ecg.BEAT_CLASSES),
                         chosen, float(ecg.FS))


def graph_subject(model_id: str, directory: Path, nodes: Any, graph: Any, hdt_id: str
                  ) -> GraphSubject:
    """The support-availability GNN on `graph` (networkx) with `nodes` (DataFrame)."""
    import torch

    from ahdt.models.ml import gnn

    meta = _read(directory)
    net = gnn._net(len(meta["features"]), int(meta["hidden"]))
    net.load_state_dict(torch.load(directory / "model.pt", weights_only=True,
                                   map_location="cpu"))
    net.eval()
    frame = nodes.reset_index(drop=True)
    x, ei = gnn._tensors(frame, graph, meta["features"], np.asarray(meta["mean"]),
                         np.asarray(meta["std"]))
    node = int(frame.index[frame.hdt_id.astype(str) == hdt_id][0])
    return GraphSubject(model_id, version_of(directory), net, x, ei, node,
                        list(meta["features"]))
