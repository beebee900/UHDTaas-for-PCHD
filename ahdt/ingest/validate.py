"""Step 2 of the pipeline: one Pandera schema per twin (design 04, 4.3.1).

The schema of a twin is generated from its definition: the field must be one of the twin's
fields, the unit must be the field's UCUM unit, and a numeric value must lie inside the
physiological plausibility bounds of `kb/plausibility.yaml`. Units are converted before
validation, so the bounds are checked in the field's own unit.
"""

from __future__ import annotations

import ast
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import pandas as pd
import pandera.pandas as pa

from ahdt.ingest.fields import FieldIndex, field_index
from atra.config import ROOT
from atra.connectors import DTKind
from atra.kb import KnowledgeBase

COLUMNS = ("field", "value", "unit", "lo", "hi", "ucum")


@dataclass(frozen=True)
class Row:
    """One harmonised value ready for validation."""

    field: str
    value: Any
    unit: str


@lru_cache(maxsize=1)
def plausibility_bounds() -> Mapping[str, Mapping[str, Any]]:
    kb = KnowledgeBase(ROOT / "kb")
    bounds: Mapping[str, Mapping[str, Any]] = kb.entry("plausibility.bounds").content()["fields"]
    return bounds


def twin_schema(twin: DTKind, index: FieldIndex) -> pa.DataFrameSchema:
    names = sorted(index.fields_of(twin))
    return pa.DataFrameSchema(
        {"field": pa.Column(str, pa.Check.isin(names)),
         "value": pa.Column(float, nullable=True),
         "unit": pa.Column(str)},
        checks=[pa.Check(lambda d: d.unit == d.ucum, name="unit",
                         error="unit differs from the field unit"),
                pa.Check(lambda d: d.value.isna() | d.lo.isna() | d.value.between(d.lo, d.hi),
                         name="plausible", error="outside physiological plausibility bounds")],
        name=f"ahdt.{twin.value}")


@lru_cache(maxsize=32)
def _schema(twin: DTKind) -> pa.DataFrameSchema:
    return twin_schema(twin, field_index())


def validate(twin: DTKind, rows: Sequence[Row]) -> dict[int, str]:
    """Row position → reason, for every row of one twin that fails its schema."""
    if not rows:
        return {}
    index, bounds = field_index(), plausibility_bounds()
    records = []
    for r in rows:
        ref = index.by_name(r.field)
        b = bounds.get(r.field, {})
        numeric = isinstance(r.value, int | float) and not isinstance(r.value, bool)
        records.append({"field": r.field, "value": float(r.value) if numeric else None,
                        "unit": r.unit, "lo": b.get("min"), "hi": b.get("max"),
                        "ucum": ref.field.ucum if ref else r.unit})
    frame = pd.DataFrame.from_records(records, columns=list(COLUMNS))
    frame["lo"] = frame["lo"].astype(float)
    frame["hi"] = frame["hi"].astype(float)
    try:
        _schema(twin).validate(frame, lazy=True)
    except pa.errors.SchemaErrors as exc:
        reasons: dict[int, str] = {}
        cases = exc.failure_cases.dropna(subset=["index"])
        for _, case in cases.iterrows():
            pos = int(case["index"])
            check = str(case["check"])
            reason = {"unit": "unit differs from the field unit",
                      "plausible": "outside physiological plausibility bounds"}.get(
                check, f"{case['column']}: {check}")
            reasons.setdefault(pos, reason)
        return reasons
    return {}


_BINOPS: Mapping[type, Any] = {
    ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b, ast.Pow: lambda a, b: a ** b}
_CMPOPS: Mapping[type, Any] = {
    ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b, ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b, ast.Eq: lambda a, b: a == b}


def _eval(node: ast.AST, values: Mapping[str, float]) -> Any:
    """Arithmetic and comparisons over field values; `abs` is the only function."""
    if isinstance(node, ast.Expression):
        return _eval(node.body, values)
    if isinstance(node, ast.Constant) and isinstance(node.value, int | float):
        return node.value
    if isinstance(node, ast.Name):
        return values[node.id]
    if isinstance(node, ast.BinOp) and type(node.op) in _BINOPS:
        return _BINOPS[type(node.op)](_eval(node.left, values), _eval(node.right, values))
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "abs":
        return abs(_eval(node.args[0], values))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, values)
        for op, comp in zip(node.ops, node.comparators, strict=True):
            right = _eval(comp, values)
            if type(op) not in _CMPOPS or not _CMPOPS[type(op)](left, right):
                return False
            left = right
        return True
    raise ValueError(f"unsupported expression node {type(node).__name__}")


@lru_cache(maxsize=1)
def plausibility_rules() -> tuple[Mapping[str, Any], ...]:
    kb = KnowledgeBase(ROOT / "kb")
    return tuple(kb.entry("plausibility.rules").content()["rules"])


def cross_field(values: Mapping[str, float]) -> list[tuple[str, list[str]]]:
    """(rule id, fields) for every consistency rule that fails on values taken together."""
    failed = []
    for rule in plausibility_rules():
        expr, fields = rule.get("expr"), rule.get("fields", [])
        if (expr and all(f in values for f in fields)
                and not _eval(ast.parse(expr, mode="eval"), values)):
            failed.append((rule["id"], list(fields)))
    return failed


def rate_limit(field: str) -> tuple[str, float, float] | None:
    """(rule id, maximum change, period in hours) for a field with a rate-of-change rule."""
    for rule in plausibility_rules():
        if rule.get("field") != field:
            continue
        if "max_change_per_hour" in rule:
            return rule["id"], float(rule["max_change_per_hour"]), 1.0
        if "max_change_per_day" in rule:
            return rule["id"], float(rule["max_change_per_day"]), 24.0
    return None
