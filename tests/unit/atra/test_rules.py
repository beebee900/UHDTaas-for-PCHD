import pytest

from atra.rules import RuleEngine, RuleError

KB = {"news2.high_min": 7, "news2.medium_min": 5, "temp.fever_c": 38.0}

RULES = [
    {"id": "band.medium", "source": "kb:news2#bands", "priority": 1,
     "when": {"fact": "news2", "op": "ge", "value": {"kb": "news2.medium_min"}},
     "then": {"band": "medium"}},
    {"id": "band.high", "source": "kb:news2#bands", "priority": 2,
     "when": {"fact": "news2", "op": "ge", "value": {"kb": "news2.high_min"}},
     "then": {"band": "high"}},
    {"id": "fever.malaria_area", "source": "kb:malaria#suspect",
     "when": {"all": [{"fact": "vitals.temp", "op": "ge", "value": {"kb": "temp.fever_c"}},
                      {"fact": "region", "op": "in", "value": ["lagos", "kano"]},
                      {"not": {"fact": "rdt", "op": "eq", "value": "negative"}}]},
     "then": {"suspect_malaria": True}},
]


def engine():
    return RuleEngine(RULES, KB.__getitem__)


def test_priority_merge_and_trace():
    r = engine().evaluate({"news2": 8})
    assert r.fired_ids() == ["band.medium", "band.high"]
    assert r.outcome["band"] == "high"
    high = next(s for s in r.trace if s.rule_id == "band.high")
    assert high.checks[0] == {"fact": "news2", "op": "ge", "actual": 8, "expected": 7,
                              "ok": True, "kb": "news2.high_min"}


def test_first_match_takes_highest_priority():
    assert engine().evaluate({"news2": 8}, first_match=True).fired_ids() == ["band.high"]


def test_nested_conditions_and_missing_facts():
    e = engine()
    assert e.evaluate({"vitals": {"temp": 38.6}, "region": "lagos"}).outcome == {
        "suspect_malaria": True}
    assert "suspect_malaria" not in e.evaluate(
        {"vitals": {"temp": 38.6}, "region": "lagos", "rdt": "negative"}).outcome
    assert e.evaluate({}).fired == []


def test_numeric_literal_is_refused():
    with pytest.raises(RuleError, match="R5"):
        RuleEngine([{"id": "x", "source": "s", "then": {},
                     "when": {"fact": "hb", "op": "lt", "value": 7}}], KB.__getitem__)


def test_duplicate_ids_refused():
    with pytest.raises(RuleError):
        RuleEngine([RULES[0], RULES[0]], KB.__getitem__)
