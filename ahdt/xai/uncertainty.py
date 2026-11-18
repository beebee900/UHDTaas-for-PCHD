"""Uncertainty reported with every explanation (design 04, 4.6.3).

- ML models: the split-conformal set or interval stored with the model (the NumPy form
  of the MAPIE 1.5 scores, see `ahdt.models.ml.conformal`).
- Mechanistic models: the polynomial-chaos band, the stored Laplace standard deviations
  as a 90 % interval, or the output range over the parameter ranges.
- Deep models: the spread of the ensemble members, and the conformal threshold.
- Language models: the self-consistency score.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ahdt.xai.mechanistic import posterior_summary
from ahdt.xai.subjects import (
    GraphSubject,
    MechanisticSubject,
    OnlineSubject,
    SequenceSubject,
    SignalSubject,
    TabularSubject,
    WindowSubject,
)
from ahdt.xai.types import Result


def _tabular(s: TabularSubject) -> dict[str, Any]:
    p = s.output
    out: dict[str, Any] = {"kind": "probability", "probability": p}
    if s.conformal is not None:
        members = [k for k, pk in enumerate((1 - p, p)) if 1 - pk <= s.conformal]
        out.update({"kind": "split_conformal", "level": s.level,
                    "prediction_set": members, "threshold": s.conformal})
    return out


def _window(s: WindowSubject) -> dict[str, Any]:
    mean = s.forecast(s.history)[:, s.target]
    out: dict[str, Any] = {"kind": "forecast", "mean": [float(v) for v in mean]}
    if s.halfwidth is not None:
        half = s.halfwidth[:len(mean), s.target]
        out.update({"kind": "split_conformal", "level": s.level,
                    "lower": float((mean - half).mean()), "upper": float((mean + half).mean()),
                    "halfwidth": [float(h) for h in half]})
    return out


def _sequence(s: SequenceSubject) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": "posterior", "probability": s.output, "state": s.target}
    if s.halfwidth is not None:
        out.update({"halfwidth_phq9": float(s.halfwidth), "level": s.level})
    return out


def _signal(s: SignalSubject) -> dict[str, Any]:
    out: dict[str, Any] = {"kind": "probability", "probability": s.output,
                           "class": s.classes[s.target]}
    members = getattr(s.net, "members", None)
    if members is not None:
        import torch

        x = torch.as_tensor(s.x[None, :], dtype=torch.float32)
        with torch.no_grad():
            probs = [float(torch.softmax(m(x), dim=1)[0, s.target]) for m in members]
        out.update({"kind": "ensemble", "members": len(probs),
                    "member_min": min(probs), "member_max": max(probs),
                    "member_std": float(np.std(probs))})
    if s.conformal is not None:
        out["conformal_threshold"] = s.conformal
        out["level"] = s.level
    return out


def _mechanistic(s: MechanisticSubject, result: Result | None) -> dict[str, Any]:
    if result is not None and result.uncertainty:
        return dict(result.uncertainty)
    if s.posterior_std:
        return dict(posterior_summary(s).uncertainty)
    from ahdt.xai.mechanistic import RANGE, factors, response

    base = factors(s)
    if not base:
        return {"kind": "none", "output": s.output_name}
    f = response(s)
    values = [f({**base, k: v * m}) for k, v in base.items() for m in (1 - RANGE, 1 + RANGE)]
    return {"kind": "parameter_range", "lower": float(min(values)), "upper": float(max(values)),
            "range": RANGE, "output": s.output_name}


def uncertainty_of(subject: Any, result: Result | None = None) -> dict[str, Any]:
    """The uncertainty block of the explanation of `subject`."""
    if isinstance(subject, TabularSubject):
        return _tabular(subject)
    if isinstance(subject, WindowSubject):
        return _window(subject)
    if isinstance(subject, SequenceSubject):
        return _sequence(subject)
    if isinstance(subject, SignalSubject):
        return _signal(subject)
    if isinstance(subject, MechanisticSubject):
        return _mechanistic(subject, result)
    if isinstance(subject, OnlineSubject):
        return {"kind": "z_score", "threshold": subject.threshold, "value": subject.output}
    if isinstance(subject, GraphSubject):
        return {"kind": "probability", "probability": subject.output}
    if result is not None and result.uncertainty:
        return dict(result.uncertainty)
    return {"kind": "deterministic"}
