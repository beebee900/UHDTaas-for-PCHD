"""XGBoost comparator and split-conformal sets for the differential (design 05, 5.5.1).

The comparator predicts the primary diagnosis from age, sex, findings and test results
(missing = not asked). Its 90 % split-conformal set uses the LAC score and the finite-sample
quantile of `ahdt.models.ml.conformal`, and is never empty (the top class is added, as MAPIE
does by default). A disagreement between its top class and the network's
top class is a signal for the clinician. The model is trained by
`evaluation.models.apdt.train` on the synthetic cohort and loaded here from its directory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ahdt.models.ml.conformal import prediction_sets
from apdt.models.context import Observations, Patient
from apdt.models.diagnosis.bn import Differential, Network, build_network
from atra.config import ROOT

MODEL_ID = "apdt.diagnosis.xgboost_comparator"
APDT_ROOT = ROOT / "var" / "models" / "apdt"
MODEL_FILE = "model.json"
META_FILE = "comparator.json"


def feature_names(net: Network) -> list[str]:
    return ["age_years", "female", *sorted(net.findings), *sorted(net.tests)]


def features(patient: Patient, obs: Observations, net: Network | None = None
             ) -> NDArray[np.float64]:
    net = net or build_network()
    row = [patient.age_years, 1.0 if patient.sex == "female" else 0.0]
    row += [float(obs.findings[f]) if f in obs.findings else np.nan for f in sorted(net.findings)]
    row += [float(obs.tests[t]) if t in obs.tests else np.nan for t in sorted(net.tests)]
    return np.asarray(row, dtype=float)


@dataclass(frozen=True)
class ComparatorOutput:
    probabilities: dict[str, float]
    conformal_set: tuple[str, ...]
    top: str
    level: float


class Comparator:
    def __init__(self, booster: Any, classes: list[str], threshold: float, level: float,
                 net: Network | None = None) -> None:
        self.booster = booster
        self.classes = classes
        self.threshold = threshold
        self.level = level
        self.net = net or build_network()

    @classmethod
    def load(cls, directory: Path | None = None) -> Comparator | None:
        d = directory or APDT_ROOT / MODEL_ID
        meta_path = d / META_FILE
        if not meta_path.exists() or not (d / MODEL_FILE).exists():
            return None
        import xgboost as xgb

        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        booster = xgb.XGBClassifier()
        booster.load_model(str(d / MODEL_FILE))
        return cls(booster, list(meta["classes"]), float(meta["threshold"]),
                   float(meta["level"]))

    def predict_proba(self, x: NDArray[np.float64]) -> NDArray[np.float64]:
        proba: NDArray[np.float64] = self.booster.predict_proba(np.atleast_2d(x))
        return proba

    def predict(self, patient: Patient, obs: Observations) -> ComparatorOutput:
        proba = self.predict_proba(features(patient, obs, self.net))[0]
        in_set = prediction_sets(proba[None, :], self.threshold)[0]
        probs = dict(zip(self.classes, (float(p) for p in proba), strict=True))
        top = self.classes[int(np.argmax(proba))]
        members = tuple(c for c, keep in zip(self.classes, in_set, strict=True) if keep) or (top,)
        return ComparatorOutput(probs, members, top, self.level)

    def disagreement(self, diff: Differential, out: ComparatorOutput) -> bool:
        """True when the network's top diagnosis is not in the conformal set."""
        top = diff.top()
        return top is not None and top.condition not in out.conformal_set
