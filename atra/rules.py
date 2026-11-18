"""JSON rule engine with a firing trace (design 01, Layer 4 "Python rule engine").

A rule is plain data:

    {"id": "news2.band.high", "source": "kb:news2#bands",
     "when": {"all": [{"fact": "news2", "op": "ge", "value": {"kb": "news2.high_min"}}]},
     "then": {"band": "high"}}

Conditions nest with `all`, `any` and `not`. A leaf compares the fact at a dotted path
with a value. Under rule R5, clinical numbers are not written into rules: a numeric value
must be a `{"kb": "<entry id>"}` reference, resolved through the knowledge base at
evaluation time. Literal strings and booleans are allowed.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

type KBResolver = Callable[[str], Any]

_MISSING = object()

_OPS: dict[str, Callable[[Any, Any], bool]] = {
    "eq": lambda a, b: bool(a == b),
    "ne": lambda a, b: bool(a != b),
    "lt": lambda a, b: bool(a < b),
    "le": lambda a, b: bool(a <= b),
    "gt": lambda a, b: bool(a > b),
    "ge": lambda a, b: bool(a >= b),
    "in": lambda a, b: a in b,
    "not_in": lambda a, b: a not in b,
    "between": lambda a, b: bool(b[0] <= a <= b[1]),
    "contains": lambda a, b: b in a,
}


class RuleError(ValueError):
    """A rule is malformed or breaks rule R5."""


@dataclass(frozen=True)
class Rule:
    id: str
    when: Mapping[str, Any]
    then: Mapping[str, Any]
    source: str
    priority: int = 0

    @classmethod
    def from_dict(cls, d: Mapping[str, Any]) -> Rule:
        for key in ("id", "when", "then", "source"):
            if key not in d:
                raise RuleError(f"rule {d.get('id', '?')} is missing '{key}'")
        rule = cls(d["id"], d["when"], d["then"], d["source"], int(d.get("priority", 0)))
        _check_r5(rule.id, rule.when)
        return rule


@dataclass
class TraceStep:
    rule_id: str
    fired: bool
    checks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class RuleResult:
    fired: list[Rule]
    outcome: dict[str, Any]
    trace: list[TraceStep]

    def fired_ids(self) -> list[str]:
        return [r.id for r in self.fired]


class RuleEngine:
    """Evaluates rules against a fact dictionary.

    `outcome` merges the `then` blocks of every fired rule in priority order (highest
    last, so it wins). `first_match=True` stops at the first fired rule instead.
    """

    def __init__(self, rules: Iterable[Rule | Mapping[str, Any]], kb: KBResolver) -> None:
        self.rules = sorted((r if isinstance(r, Rule) else Rule.from_dict(r) for r in rules),
                            key=lambda r: r.priority)
        ids = [r.id for r in self.rules]
        if len(ids) != len(set(ids)):
            raise RuleError("duplicate rule ids")
        self.kb = kb

    def evaluate(self, facts: Mapping[str, Any], *, first_match: bool = False) -> RuleResult:
        fired: list[Rule] = []
        outcome: dict[str, Any] = {}
        trace: list[TraceStep] = []
        ordered: Sequence[Rule] = list(reversed(self.rules)) if first_match else self.rules
        for rule in ordered:
            step = TraceStep(rule.id, False)
            if self._cond(rule.when, facts, step):
                step.fired = True
                fired.append(rule)
                outcome.update(rule.then)
            trace.append(step)
            if first_match and step.fired:
                break
        return RuleResult(fired, outcome, trace)

    def _cond(self, cond: Mapping[str, Any], facts: Mapping[str, Any], step: TraceStep) -> bool:
        if "all" in cond:
            return all(self._cond(c, facts, step) for c in cond["all"])
        if "any" in cond:
            return any(self._cond(c, facts, step) for c in cond["any"])
        if "not" in cond:
            return not self._cond(cond["not"], facts, step)
        fact, op = cond["fact"], cond["op"]
        actual = lookup(facts, fact)
        if op == "exists":
            ok = actual is not _MISSING and actual is not None
            step.checks.append({"fact": fact, "op": op, "actual": _show(actual), "ok": ok})
            return ok
        expected = self._value(cond.get("value"))
        if actual is _MISSING or actual is None:
            ok = False
        else:
            try:
                ok = _OPS[op](actual, expected)
            except KeyError as exc:
                raise RuleError(f"{step.rule_id}: unknown operator {op}") from exc
            except TypeError:
                ok = False
        step.checks.append({"fact": fact, "op": op, "actual": _show(actual),
                            "expected": expected, "ok": ok,
                            **({"kb": cond["value"]["kb"]} if _is_kb(cond.get("value")) else {})})
        return ok

    def _value(self, value: Any) -> Any:
        if _is_kb(value):
            return self.kb(value["kb"])
        if isinstance(value, list):
            return [self._value(v) for v in value]
        return value


def lookup(facts: Mapping[str, Any], path: str) -> Any:
    cur: Any = facts
    for part in path.split("."):
        if isinstance(cur, Mapping) and part in cur:
            cur = cur[part]
        else:
            return _MISSING
    return cur


def _is_kb(value: Any) -> bool:
    return isinstance(value, Mapping) and set(value) == {"kb"}


def _show(value: Any) -> Any:
    return None if value is _MISSING else value


def _check_r5(rule_id: str, cond: Any) -> None:
    if isinstance(cond, Mapping):
        if "fact" in cond and "value" in cond:
            _check_value(rule_id, cond["value"])
        for v in cond.values():
            if isinstance(v, Mapping | list):
                _check_r5(rule_id, v)
    elif isinstance(cond, list):
        for c in cond:
            _check_r5(rule_id, c)


def _check_value(rule_id: str, value: Any) -> None:
    if isinstance(value, bool) or _is_kb(value) or isinstance(value, str) or value is None:
        return
    if isinstance(value, int | float):
        raise RuleError(f"{rule_id}: numeric literal {value}; reference a kb entry instead (R5)")
    if isinstance(value, list):
        for v in value:
            _check_value(rule_id, v)
