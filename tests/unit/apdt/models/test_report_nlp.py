"""River anomaly streams and medspaCy report reading."""

from __future__ import annotations

import numpy as np

from apdt.models.context import Observations
from apdt.models.diagnosis import report_nlp
from apdt.models.diagnosis.anomaly import LabStream


def test_report_negation_and_apply() -> None:
    mentions = report_nlp.read_report(
        "The patient has fever and cough. No haemoptysis. Possible chest pain.")
    by = {m.finding: m for m in mentions}
    assert by["find.fever"].present and by["find.cough"].present
    assert not by["find.haemoptysis"].present
    assert by["find.chest_pain"].uncertain
    obs = Observations()
    report_nlp.apply_to(obs, "Fever. No haemoptysis. Possible chest pain.")
    assert obs.findings == {"find.fever": True, "find.haemoptysis": False}


def test_lab_stream_flags_a_jump_after_warmup() -> None:
    rng = np.random.default_rng(0)
    stream = LabStream("creatinine", seed=1)
    scores = [stream.update(float(90 + rng.normal(0, 4))) for _ in range(120)]
    assert not any(s.flagged for s in scores[:50])
    typical = np.mean([s.score for s in scores[60:]])
    spike = stream.update(900.0)
    assert spike.score > typical and spike.score > 0.5
