"""Critical-result paging (design 05, 5.3): `kb/critical_values.yaml` rules → `alert.raised`
to the responsible clinician, with an SMS page through the channels service as fallback.

A rule compares one twin field (in the field's UCUM unit) with a cut-off read from a
sourced kb entry. `child` rules apply under 16 years (RCPath G158). When the age is not
known, rules of both populations apply, so no critical value goes unpaged.
"""

from __future__ import annotations

import operator
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from ahdt.ingest.fields import FieldIndex, field_index
from atra import units
from atra.backends import Backends
from atra.contracts import Code, EventEnvelope
from atra.ids import uuid7
from atra.kb import KnowledgeBase

OPS: Mapping[str, Callable[[float, float], bool]] = {
    "lt": operator.lt, "le": operator.le, "gt": operator.gt, "ge": operator.ge}
CHILD_UNDER_YEARS = 16


@dataclass(frozen=True)
class Hit:
    rule_id: str
    field: str
    value: float
    unit: str
    threshold: float
    op: str
    urgency: str


class CriticalRules:
    def __init__(self, kb: KnowledgeBase, index: FieldIndex | None = None) -> None:
        self.kb = kb
        self.index = index or field_index()
        self.rules: list[dict[str, Any]] = list(kb.entry("critical.rules").content()["rules"])

    def _threshold(self, rule: Mapping[str, Any], field_unit: str) -> float:
        value = float(self.kb.lookup(rule["threshold"], rule["path"]))
        parent = rule["path"].rsplit(".", 1)[0] if "." in rule["path"] else None
        unit = None
        if parent and "[" not in parent:
            try:
                unit = self.kb.lookup(rule["threshold"], f"{parent}.unit")
            except KeyError:
                unit = None
        if unit and unit != field_unit:
            value = units.convert(value, str(unit), field_unit)
        return value

    def check(self, code: Code, value: float, unit: str, *,
              age_years: float | None = None) -> list[Hit]:
        """The rules a value meets, most urgent first."""
        ref = self.index.resolve(code)
        if ref is None:
            return []
        target = ref.field.ucum
        if unit != target:
            value = units.convert(value, unit, target, substance=ref.field.name
                                  if ref.field.name in units.MOLAR_MASS else None)
        population = (None if age_years is None
                      else "child" if age_years < CHILD_UNDER_YEARS else "adult")
        hits = []
        for rule in self.rules:
            if rule["field"] != ref.field.name:
                continue
            if rule["population"] != "any" and population not in (None, rule["population"]):
                continue
            cut = self._threshold(rule, target)
            if OPS[rule["op"]](value, cut):
                hits.append(Hit(rule["id"], ref.field.name, value, target, cut, rule["op"],
                                rule["urgency"]))
        return sorted(hits, key=lambda h: h.urgency != "emergency")


type Pager = Callable[[Mapping[str, Any]], Awaitable[None]]


class CriticalPager:
    """Raises `alert.raised` for each critical result and asks the SMS pager to page."""

    def __init__(self, backends: Backends, rules: CriticalRules, *,
                 sms_page: Pager | None = None) -> None:
        self.backends = backends
        self.rules = rules
        self.sms_page = sms_page

    async def page(self, observation: Mapping[str, Any], *, tenant_id: str, hdt_id: str,
                   episode_id: str, clinician: str,
                   age_years: float | None = None) -> list[dict[str, Any]]:
        q = observation.get("valueQuantity")
        if not q or "value" not in q:
            return []
        alerts = []
        for coding in observation["code"]["coding"]:
            code = Code(system=coding["system"], code=coding["code"])
            hits = self.rules.check(code, float(q["value"]), str(q.get("code") or q.get("unit")),
                                    age_years=age_years)
            if not hits:
                continue
            hit = hits[0]
            now = datetime.now(UTC)
            alert = {"alert_id": f"alert-{uuid7()}", "severity": hit.urgency,
                     "to": {"role": "medical_officer", "id": clinician},
                     "reason": (f"critical {hit.field} {hit.value:g} {hit.unit} "
                                f"({hit.op} {hit.threshold:g}, rule {hit.rule_id})"),
                     "bundle_id": None,
                     "due_by": now.isoformat() if hit.urgency == "emergency" else None,
                     "observation": f"Observation/{observation['id']}"}
            await self.backends.events.publish(EventEnvelope(
                event_id=f"evt-{uuid7()}", event_type="alert.raised", source="apdt",
                hdt_id=hdt_id, tenant_id=tenant_id, episode_id=episode_id, wall_time=now,
                trace_id=uuid7().hex, payload=alert))
            if self.sms_page is not None:
                await self.sms_page({**alert, "tenant_id": tenant_id})
            alerts.append(alert)
            break
        return alerts
