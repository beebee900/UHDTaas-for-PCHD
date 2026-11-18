"""Vendor cloud simulators: response bodies in the vendors' documented formats, for the
adapters in `ahdt.devices.vendors` to fetch through an injected HTTP client."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from atra import units
from edge.devices.sim.base import Simulator, seed_of

EGV_PERIOD_S = 300.0
EGV_LOW, EGV_HIGH = 40, 400


@dataclass
class DexcomCloud(Simulator):
    """GET /v3/users/self/egvs: one EGV every 5 min in mg/dL from a receiver (no UTC offset).
    Values outside 40-400 are reported as 39 or 401 with status low or high, as the API
    reference describes."""

    def egvs(self) -> dict[str, Any]:
        records = []
        for n, t in enumerate(self.schedule("glucose", EGV_PERIOD_S)):
            mg = round(units.convert(self.measure("glucose", t), "mmol/L", "mg/dL",
                                     substance="glucose"))
            status = "low" if mg < EGV_LOW else "high" if mg > EGV_HIGH else None
            when = self.stream.when(t).replace(tzinfo=None).isoformat(timespec="seconds")
            records.append({
                "recordId": str(uuid.UUID(int=seed_of(self.device_id, str(n)) << 64)),
                "systemTime": when, "displayTime": when, "transmitterId": None,
                "transmitterTicks": int(t), "value": min(max(mg, 39), 401), "status": status,
                "trend": "flat", "trendRate": 0.0, "unit": "mg/dL", "rateUnit": "mg/dL/min",
                "displayDevice": "receiver", "transmitterGeneration": "g7",
                "transmitterGenerationVariant": "g7", "displayApp": "G7"})
        return {"recordType": "egv", "recordVersion": "3.0", "userId": self.hdt_id,
                "records": records}
