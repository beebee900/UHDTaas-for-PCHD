"""MCDA, decision aid and capacity rules."""

from __future__ import annotations

import numpy as np
import pytest

from apdt.models.agency import capacity, decision_aid, mcda
from apdt.models.reasoning import ClinicalReasoner
from evaluation.models.apdt.scenarios import BY_SCENARIO


def test_swing_weights_normalise() -> None:
    w = mcda.swing_weights({"effectiveness": 100, "cost_to_patient": 50, "route": 50})
    assert sum(w.values()) == pytest.approx(1.0) and w["effectiveness"] == pytest.approx(0.5)
    with pytest.raises(ValueError):
        mcda.swing_weights({"colour": 10})


def test_paired_choices_recover_the_dominant_criterion() -> None:
    rng = np.random.default_rng(1)
    choices = []
    for _ in range(40):
        a = {"effectiveness": float(rng.random()), "cost_to_patient": float(rng.random() * 1000),
             "route": float(rng.random())}
        b = {"effectiveness": float(rng.random()), "cost_to_patient": float(rng.random() * 1000),
             "route": float(rng.random())}
        choices.append(mcda.PairedChoice(a, b, "a" if a["effectiveness"] > b["effectiveness"]
                                         else "b"))
    w = mcda.paired_choice_weights(choices)
    assert sum(w.values()) == pytest.approx(1.0)
    assert max(w, key=lambda c: w[c]) == "effectiveness"


def test_scoring_follows_the_weights() -> None:
    options = {"cheap": {"effectiveness": 0.8, "cost_to_patient": 500.0},
               "dear": {"effectiveness": 0.9, "cost_to_patient": 5000.0}}
    assert mcda.score_options({"effectiveness": 0.9, "cost_to_patient": 0.1}, options
                              )[0].option_id == "dear"
    assert mcda.score_options({"effectiveness": 0.1, "cost_to_patient": 0.9}, options
                              )[0].option_id == "cheap"


def test_missing_criteria_are_left_out() -> None:
    scored = mcda.score_options({"effectiveness": 0.5, "route": 0.5},
                                {"a": {"effectiveness": 1.0}, "b": {"effectiveness": 0.0,
                                                                     "route": 0.0}})
    assert scored[0].option_id == "a" and set(scored[0].contributions) == {"effectiveness"}


def test_route_burden_orders_routes() -> None:
    assert mcda.option_attributes(2, "oral")["route"] < mcda.option_attributes(1, "intravenous")[
        "route"]


def test_capacity_rules() -> None:
    assert capacity.decide(8).actor == "guardian"
    adult = capacity.decide(40)
    assert adult.actor == "self" and not adult.escalate
    unconscious = capacity.decide(40, avpu="V", has_registered_proxy=False)
    assert unconscious.actor == "registered_proxy" and unconscious.escalate
    assert not capacity.decide(40, avpu="V", has_registered_proxy=True).escalate
    assessed = capacity.decide(40, capacity_assessment="lacks_capacity")
    assert assessed.rule_id == "assessed_lacks_capacity"
    assert assessed.audit["rule"] == "assessed_lacks_capacity" and assessed.audit["checks"]
    assert capacity.decide(17).rule_id == "minor" and capacity.decide(18).rule_id == "default"


def test_decision_aid_grid_has_sources() -> None:
    s = BY_SCENARIO["gh"]
    a = ClinicalReasoner().assess(s.patient, s.observations, with_tests=False)
    grid = decision_aid.build(a.options["cond.tb_pulmonary"].eligible, language="en")
    row = grid["options"][0]
    assert row["benefits"][0]["citation"] and row["harms"]
    assert row["harms"][0]["source"] == "ix.dolutegravir.rifampicin"
    assert grid["audio"]["text"].startswith(row["name"])
    adapted = decision_aid.build(a.options["cond.tb_pulmonary"].eligible, language="yo",
                                 literacy="low", adapt=lambda t, lang, lvl: f"[{lang}/{lvl}] {t}")
    assert adapted["options"][0]["text"].startswith("[yo/low]")


def test_literacy_screening_levels() -> None:
    assert decision_aid.literacy_level(0) == "low" and decision_aid.literacy_level(3) == "high"
    with pytest.raises(ValueError):
        decision_aid.literacy_level(5)
