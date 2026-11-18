"""Source-state view and the declarative field rules of the connector mappings.

A connector's source state is a mapping with up to four sections:

- `state`: the merged states of the organ instances the twin owns (WP14a store);
- `units`: the UCUM unit of each `state` value (from the model output ports);
- `fields`: the person's latest observation per registry field, `{name: {value, unit}}`;
- `context`: values without a unit (demographics, conditions, event details).

Top-level keys outside these sections count as context, so an APDT record or an event
can be published as it is. A rule names its candidates as `state:<name>`, `field:<name>`
or `context:<name>` and takes the first one that is present and convertible to the
contract unit. A value that no candidate provides is left out, so the contract check
reports it as missing.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

from atra.connectors import DataContract, FieldSpec
from atra.units import UnitError, convert

SECTIONS = ("state", "units", "fields", "context", "_models")

# UCUM `[pH]` is dimensionless; the contracts write it as `1`.
_SAME_UNIT = frozenset({("[pH]", "1")})


@dataclass(frozen=True)
class Raw:
    value: Any
    unit: str | None


class SourceView:
    """Read access to one source state by `kind:name` reference."""

    def __init__(self, source_state: Mapping[str, Any]) -> None:
        self.raw = source_state
        self.state: Mapping[str, Any] = source_state.get("state") or {}
        self.units: Mapping[str, str] = source_state.get("units") or {}
        self.fields: Mapping[str, Mapping[str, Any]] = source_state.get("fields") or {}
        context = dict(source_state.get("context") or {})
        for key, value in source_state.items():
            if key not in SECTIONS:
                context.setdefault(key, value)
        self.context: Mapping[str, Any] = context

    def get(self, ref: str) -> Raw | None:
        kind, _, name = ref.partition(":")
        if kind == "state" and self.state.get(name) is not None:
            return Raw(self.state[name], self.units.get(name))
        if kind == "field":
            obs = self.fields.get(name)
            if obs is not None and obs.get("value") is not None:
                return Raw(obs["value"], obs.get("unit"))
        if kind == "context" and self.context.get(name) is not None:
            return Raw(self.context[name], None)
        if kind not in ("state", "field", "context"):
            raise ValueError(f"unknown source reference '{ref}'")
        return None

    def value(self, ref: str, unit: str | None = None) -> Any:
        """The value of `ref` in `unit`, or None when absent or not convertible."""
        raw = self.get(ref)
        if raw is None:
            return None
        return to_unit(raw, unit)

    def first(self, refs: tuple[str, ...], unit: str | None = None) -> Any:
        for ref in refs:
            value = self.value(ref, unit)
            if value is not None:
                return value
        return None

    def conditions(self) -> set[str] | None:
        found = self.context.get("conditions")
        return None if found is None else {str(c) for c in found}


def to_unit(raw: Raw, unit: str | None) -> Any:
    value = raw.value
    if unit is None or raw.unit is None or raw.unit == unit or (raw.unit, unit) in _SAME_UNIT:
        return value
    if isinstance(value, bool) or not isinstance(value, int | float):
        return value
    try:
        return convert(float(value), raw.unit, unit)
    except UnitError:
        return None


type Derive = Callable[[SourceView], Any]


@dataclass(frozen=True)
class Rule:
    """One contract field: candidate sources in order, or a derivation."""

    field: str
    sources: tuple[str, ...] = ()
    derive: Derive | None = None


def take(field: str, *sources: str) -> Rule:
    return Rule(field, sources)


def derived(field: str, fn: Derive) -> Rule:
    return Rule(field, derive=fn)


def _typed(spec: FieldSpec, value: Any) -> Any:
    if spec.dtype == "bool" and isinstance(value, int | float) and not isinstance(value, bool):
        return value >= 0.5  # 0/1 indicator states
    if spec.dtype == "float" and isinstance(value, int) and not isinstance(value, bool):
        return float(value)
    return value


def apply_rules(rules: tuple[Rule, ...], contract: DataContract,
                source_state: Mapping[str, Any]) -> dict[str, Any]:
    """The contract payload the rules produce from one source state."""
    view = SourceView(source_state)
    payload: dict[str, Any] = {}
    for rule in rules:
        spec = contract.fields[rule.field]
        value = rule.derive(view) if rule.derive else view.first(rule.sources, spec.unit)
        if value is not None:
            payload[rule.field] = _typed(spec, value)
    return payload


def flag_or_condition(flag: str, condition: str) -> Derive:
    """The boolean context value `flag`, else whether `condition` (a kb condition id) is
    recorded; absent when neither is known."""

    def fn(view: SourceView) -> bool | None:
        value = view.context.get(flag)
        if isinstance(value, bool):
            return value
        found = view.conditions()
        return None if found is None else condition in found

    return fn
