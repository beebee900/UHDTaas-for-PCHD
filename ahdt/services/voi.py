"""Value-of-information acquisition policy (design 04, 4.7.5).

For each freshness goal of a twin, a field with no reading or an old reading leaves the
goal check uncertain. The expected reduction in that uncertainty is the field's staleness:
the age of its newest reading over the goal's maximum age, capped at 1, and 1 when the field
was never measured. It is divided by the burden of obtaining the field, an ordinal cost
by capture source (automatic capture 1, manual measurement 2, self-report 3, laboratory
4, imaging 5). The result ranks the data requests that most improve the goal checks per
unit of burden. The burden scale is ordinal, not a measured quantity.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ahdt.services.runtime import Runtime
from atra.connectors import DTKind

BURDEN = {"device": 1, "monitor": 1, "wearable": 1, "derived": 1, "import": 1, "manual": 2,
          "self_report": 3, "lab": 4, "imaging": 5}
SOURCE_OF = {"device": "device", "monitor": "device", "wearable": "device",
             "derived": "device", "import": "clinician", "manual": "clinician",
             "self_report": "person", "lab": "clinician", "imaging": "clinician"}


@dataclass(frozen=True)
class Acquisition:
    field: str
    twin: DTKind
    goal_id: str
    voi: float
    staleness: float
    burden: int
    source: str
    age_s: float | None


async def rank(runtime: Runtime, hdt_id: str, kinds: list[DTKind] | None = None, *,
               now: datetime | None = None) -> list[Acquisition]:
    """Acquisitions for the freshness goals of `kinds` (all person twins by default),
    highest value per burden first."""
    reader = await runtime.reader()
    now = now or datetime.now(UTC)
    found: dict[tuple[DTKind, str], Acquisition] = {}
    for kind in kinds or list(runtime.registry.twins):
        definition = runtime.registry.get(kind)
        if definition is None:
            continue
        fields = {f.name: f for f in definition.fields}
        latest = reader.latest(hdt_id, as_of=now, twin=kind)
        newest = {reader.field_name(r.code): r.effective_time for r in latest.values()}
        for goal in definition.standing_goals:
            if goal.check.kind != "freshness":
                continue
            max_age = float(goal.check.params["max_age_s"])
            for name in goal.check.params["fields"]:
                age = (now - newest[name]).total_seconds() if name in newest else None
                stale = 1.0 if age is None else min(1.0, max(age, 0.0) / max_age)
                sources = fields[name].source if name in fields else ["manual"]
                best = min(sources, key=lambda s: BURDEN[s])
                item = Acquisition(name, kind, goal.id, stale / BURDEN[best], stale,
                                   BURDEN[best], SOURCE_OF[best], age)
                if item.voi > found.get((kind, name), item).voi or (kind, name) not in found:
                    found[(kind, name)] = item
    return sorted((a for a in found.values() if a.voi > 0), key=lambda a: -a.voi)
