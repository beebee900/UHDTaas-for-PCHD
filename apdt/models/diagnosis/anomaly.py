"""Streaming anomaly scores on lab trends with River HalfSpaceTrees (design 05, 5.5.1).

Each lab field has its own stream. Values are scaled to [0, 1] with the field's plausible
range from `plausibility.bounds`. A result is scored before the stream learns it, so the
score measures how unusual the value is for that person's history. Scores in the warm-up
period are not flagged.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from apdt.models.context import kb, param


@dataclass(frozen=True)
class Scored:
    value: float
    score: float
    flagged: bool


@dataclass
class LabStream:
    field_name: str
    seed: int = 0
    seen: int = 0
    _model: Any = field(default=None, repr=False)
    _lo: float = 0.0
    _hi: float = 1.0

    def __post_init__(self) -> None:
        from river import anomaly

        cfg = param("anomaly")
        bounds = kb().entry("plausibility.bounds").content()["fields"][self.field_name]
        self._lo, self._hi = float(bounds["min"]), float(bounds["max"])
        self._model = anomaly.HalfSpaceTrees(n_trees=int(cfg["trees"]), height=int(cfg["height"]),
                                             window_size=int(cfg["window"]), seed=self.seed)

    def _x(self, value: float) -> dict[str, float]:
        scaled = (value - self._lo) / (self._hi - self._lo)
        return {self.field_name: min(max(scaled, 0.0), 1.0)}

    def update(self, value: float) -> Scored:
        cfg = param("anomaly")
        x = self._x(value)
        score = float(self._model.score_one(x))
        self._model.learn_one(x)
        self.seen += 1
        return Scored(value, score, self.seen > int(cfg["warmup"])
                      and score >= float(cfg["flag_score"]))
