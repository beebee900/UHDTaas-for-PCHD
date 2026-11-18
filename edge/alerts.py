"""Local alerts at the edge (design 04, 4.2.1 tier 2; design 07, 7.7 power resilience).

The edge raises alerts without the cloud from two sources:
- the critical-value rules of `kb/critical_values.yaml`, each reading its cut-off from the
  sourced kb entry it names (design 01, R5), applied to every scalar reading;
- the detections of the ONNX edge models whose probability reaches their operating point.

An alert goes to the person's phone as a notification. An `emergency` alert also goes by SMS
through the channels service when the link is `offline` or the AHDT cannot be reached. Both are
actuator commands, so they pass the autonomy check of `edge.actuators` and are audited. A rule
that fired for a person does not fire again for `repeat_after_s`.
"""

from __future__ import annotations

import operator
import sqlite3
import threading
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from ahdt.ingest.fields import FieldIndex, field_index
from atra import units
from atra.config import ROOT
from atra.contracts import Actor, Code
from atra.ids import new_record_id
from atra.kb import KnowledgeBase
from edge.actuators.autonomy import AutonomyDenied
from edge.actuators.service import ActuationResult, ActuationService, Command
from edge.inference import Detection

AGENT = "edge.alerts"
ACTOR = Actor(id="edge-alerts", role="service")
OPS: dict[str, Callable[[float, float], bool]] = {
    "lt": operator.lt, "le": operator.le, "gt": operator.gt, "ge": operator.ge}

type Urgency = Literal["emergency", "urgent", "routine"]
type Population = Literal["adult", "child"]


@dataclass(frozen=True)
class CriticalRule:
    rule_id: str
    field: str
    code: Code
    unit: str
    op: str
    threshold: float
    population: str
    urgency: Urgency

    def applies(self, population: Population) -> bool:
        return self.population in ("any", population)

    def breached(self, value: float) -> bool:
        return OPS[self.op](value, self.threshold)


@lru_cache(maxsize=1)
def critical_rules(kb_dir: Path = ROOT / "kb") -> tuple[CriticalRule, ...]:
    kb = KnowledgeBase(kb_dir)
    index = field_index()
    out = []
    for r in kb.entry("critical.rules").content()["rules"]:
        ref = index.by_name(r["field"])
        if ref is None:
            continue
        out.append(CriticalRule(r["id"], r["field"], ref.code, ref.field.ucum, r["op"],
                                float(kb.lookup(r["threshold"], r["path"])), r["population"],
                                r["urgency"]))
    return tuple(out)


@dataclass(frozen=True)
class Alert:
    alert_id: str
    hdt_id: str
    source: Literal["rule", "model"]
    rule: str
    urgency: Urgency
    time: datetime
    field: str | None = None
    value: float | None = None
    unit: str | None = None
    probability: float | None = None

    @property
    def text(self) -> str:
        at = self.time.astimezone(UTC).strftime("%H:%M UTC")
        if self.source == "model":
            return f"ATRA {self.urgency} alert: {self.rule} detected at {at}."
        return f"ATRA {self.urgency} alert: {self.field} {self.value:g} {self.unit} at {at}."


class AlertRules:
    def __init__(self, rules: Iterable[CriticalRule] | None = None, *,
                 index: FieldIndex | None = None,
                 population_of: Callable[[str], Population] = lambda _: "adult") -> None:
        self.rules = tuple(critical_rules() if rules is None else rules)
        self.index = index or field_index()
        self.population_of = population_of

    def evaluate(self, payloads: Iterable[Mapping[str, Any]]) -> list[Alert]:
        out = []
        for p in payloads:
            v = p["value"]
            if not isinstance(v, int | float) or isinstance(v, bool):
                continue
            ref = self.index.resolve(Code.model_validate(p["code"]))
            if ref is None:
                continue
            population = self.population_of(str(p["hdt_id"]))
            for rule in self.rules:
                if rule.field != ref.field.name or not rule.applies(population):
                    continue
                value = float(v) if p["unit"] == rule.unit else units.convert(
                    float(v), str(p["unit"]), rule.unit)
                if rule.breached(value):
                    out.append(Alert(new_record_id(), str(p["hdt_id"]), "rule", rule.rule_id,
                                     rule.urgency,
                                     datetime.fromisoformat(str(p["effective_time"])),
                                     rule.field, value, rule.unit))
        return out


def from_detections(detections: Iterable[Detection]) -> list[Alert]:
    return [Alert(new_record_id(), d.hdt_id, "model", d.alert.label, d.alert.urgency, d.time,
                  probability=d.probabilities[d.alert.label])
            for d in detections if d.fires and d.alert is not None]


_SCHEMA = """CREATE TABLE IF NOT EXISTS alerts (
    alert_id TEXT PRIMARY KEY, hdt_id TEXT NOT NULL, source TEXT NOT NULL, rule TEXT NOT NULL,
    urgency TEXT NOT NULL, time TEXT NOT NULL, field TEXT, value REAL, unit TEXT,
    probability REAL, notified TEXT, sms TEXT)"""


@dataclass(frozen=True)
class Dispatched:
    alert: Alert
    notify: ActuationResult | None
    sms: ActuationResult | None


class AlertDispatcher:
    """Keeps the edge's alert log and sends each new alert through the actuators."""

    def __init__(self, actuation: ActuationService, path: Path | None = None, *,
                 repeat_after_s: float = 900.0) -> None:
        self.actuation = actuation
        self.repeat_after = timedelta(seconds=repeat_after_s)
        self._last: dict[tuple[str, str], datetime] = {}
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self._db.execute(_SCHEMA)
        self._db.commit()

    def _new(self, alert: Alert) -> bool:
        key = (alert.hdt_id, alert.rule)
        last = self._last.get(key)
        if last is not None and alert.time - last < self.repeat_after:
            return False
        self._last[key] = alert.time
        return True

    async def _send(self, alert: Alert, actuator: str,
                    params: dict[str, Any]) -> ActuationResult | None:
        command = Command(command_id=new_record_id(), hdt_id=alert.hdt_id, actuator=actuator,
                          agent=AGENT, actor=ACTOR, purpose="care", params=params)
        try:
            return await self.actuation.request(command)
        except AutonomyDenied:
            return self.actuation.results[-1]

    async def dispatch(self, alerts: Iterable[Alert], *, sms: bool) -> list[Dispatched]:
        out = []
        for a in alerts:
            if not self._new(a):
                continue
            notify = await self._send(a, "notify", {"title": f"ATRA {a.urgency} alert",
                                                    "body": a.text})
            text = await self._send(a, "sms", {"body": a.text}) if (
                sms and a.urgency == "emergency") else None
            with self._lock:
                self._db.execute(
                    "INSERT INTO alerts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (a.alert_id, a.hdt_id, a.source, a.rule, a.urgency, a.time.isoformat(),
                     a.field, a.value, a.unit, a.probability,
                     notify.outcome if notify else None, text.outcome if text else None))
                self._db.commit()
            out.append(Dispatched(a, notify, text))
        return out

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock:
            cur = self._db.execute("SELECT * FROM alerts ORDER BY time DESC LIMIT ?", (limit,))
            names = [c[0] for c in cur.description]
            return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
