"""The APDT's view of the AHDT, always through the ATRA gateway (design 05, 5.7 and 5.8.1).

Every call runs with the acting clinician's role. When the AHDT cannot answer, or the role or
the patient's consent forbids the call, the result lists what is missing and the APDT items
are still returned.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
from typing import Any

import httpx

from atra import contracts as c
from atra.connectors import DTKind
from atra.consent import ConsentRegistry
from atra.gateway import (
    AHDTRefused,
    AHDTServiceGateway,
    CallContext,
    GatewayDenied,
    RESTBackend,
    ToolResult,
)

VITAL_CODES: Mapping[str, tuple[str, str]] = {
    "8310-5": ("temperature", "Temperature"), "8867-4": ("heart_rate", "Heart rate"),
    "8480-6": ("systolic_bp", "Systolic blood pressure"),
    "8462-4": ("diastolic_bp", "Diastolic blood pressure"),
    "9279-1": ("respiratory_rate", "Respiratory rate"), "59408-5": ("spo2", "Oxygen saturation")}
SIMULATION_TWINS = ["renal_urinary", "hepatobiliary", "whole_body"]
FORECAST = {"dt": "immune_lymphatic", "variable": "temperature", "horizon_h": 24}
SERIES_SHOWN = 3
TIMEOUT_S = 30.0


class Missing(Exception):
    """An AHDT call that gave no data; `reason` names the evidence that is absent."""

    def __init__(self, tool: str, reason: str) -> None:
        super().__init__(f"{tool}: {reason}")
        self.tool = tool
        self.reason = reason


class AHDTAccess:
    def __init__(self, ahdt_url: str, token: Callable[[], str], consents: ConsentRegistry,
                 client: httpx.AsyncClient | None = None) -> None:
        self.ahdt_url = ahdt_url
        self.token = token
        self.consents = consents
        self.client = client
        self._pooled: tuple[asyncio.AbstractEventLoop, httpx.AsyncClient] | None = None
        self._gateways: dict[str, AHDTServiceGateway] = {}

    def http(self) -> httpx.AsyncClient:
        """The given client, else one connection pool per event loop."""
        if self.client is not None:
            return self.client
        loop = asyncio.get_running_loop()
        if self._pooled is None or self._pooled[0] is not loop:
            self._pooled = (loop, httpx.AsyncClient(timeout=TIMEOUT_S))
            self._gateways.clear()
        return self._pooled[1]

    def gateway(self, tenant_id: str) -> AHDTServiceGateway:
        client = self.http()
        gw = self._gateways.get(tenant_id)
        if gw is None:
            from atra.contracts import ATRA_ROLE_TOOLS

            backend = RESTBackend(self.ahdt_url, self.token, tenant_id=tenant_id,
                                  client=client)
            gw = AHDTServiceGateway(backend, {}, role_tools=ATRA_ROLE_TOOLS, max_retries=1,
                                    backoff_s=0.05, timeout_s=TIMEOUT_S)
            self._gateways[tenant_id] = gw
        gw.consents = self.consents.as_mapping()
        return gw

    async def call(self, tenant_id: str, tool: str, args: Mapping[str, Any],
                   ctx: CallContext) -> dict[str, Any]:
        """The data of one AHDT tool, or `Missing` with the reason."""
        try:
            result: ToolResult = await self.gateway(tenant_id).call(tool, args, ctx=ctx)
        except GatewayDenied as exc:
            raise Missing(tool, f"not permitted ({exc})") from exc
        except AHDTRefused as exc:
            raise Missing(tool, f"refused by the AHDT ({exc})") from exc
        except (httpx.HTTPError, ValueError, KeyError) as exc:
            raise Missing(tool, f"failed ({exc})") from exc
        if result.degraded:
            raise Missing(tool, result.error or "AHDT evidence unavailable")
        return result.data

    async def vitals(self, tenant_id: str, ctx: CallContext) -> dict[str, c.SourcedItem]:
        data = await self.call(tenant_id, "ahdt.data.observations",
                               {"codes": list(VITAL_CODES)}, ctx)
        out: dict[str, c.SourcedItem] = {}
        for code, points in data.get("series", {}).items():
            if code not in VITAL_CODES or not points:
                continue
            key, label = VITAL_CODES[code]
            last = max(points, key=lambda p: p["t"])
            out[key] = c.SourcedItem(source="ahdt", kind="vital", label=label, value=last["v"],
                                     unit=last.get("unit"), time=_time(last["t"]), ref=code)
        return out

    async def medications(self, tenant_id: str, ctx: CallContext) -> list[c.SourcedItem]:
        data = await self.call(tenant_id, "ahdt.data.medications", {"active_only": True}, ctx)
        return [c.SourcedItem(source="ahdt", kind="medication", label=m["display"],
                              value=f"{m['dose']} {m['frequency']}".strip(), time=_time(m["start"]),
                              ref=m["atc"]) for m in data.get("medications", [])]

    async def tile(self, tenant_id: str, kind: DTKind, ctx: CallContext) -> c.TwinTile:
        try:
            data = await self.call(tenant_id, "ahdt.model.state", {"dt": kind.value}, ctx)
        except Missing as exc:
            return c.TwinTile(dt=kind, status="unavailable", headline=exc.reason)
        numbers = [(k, v) for k, v in data["state"].items()
                   if isinstance(v, int | float) and not isinstance(v, bool)]
        headline = ("; ".join(f"{k.replace('_', ' ')} {v:.4g}" for k, v in numbers[:2])
                    if numbers else "No readings yet")
        return c.TwinTile(dt=kind, status=data["status"], headline=headline,
                          updated_at=_time(data["updated_at"]))

    async def forecast(self, tenant_id: str, ctx: CallContext) -> dict[str, Any] | None:
        try:
            data = await self.call(tenant_id, "ahdt.model.forecast", FORECAST, ctx)
        except Missing:
            return None
        return {"variable": FORECAST["variable"], "horizon_h": FORECAST["horizon_h"], **data}

    async def simulate(self, tenant_id: str, scenario: Mapping[str, Any], ctx: CallContext,
                       assumptions: list[str], horizon_h: float = 72) -> c.SimulationTrace:
        """A forked what-if on the person's twins, summarised as a bundle trace."""
        data = await self.call(tenant_id, "ahdt.model.simulate",
                               {"dt": SIMULATION_TWINS[0], "scenario": dict(scenario),
                                "horizon_h": horizon_h}, ctx)
        traj = c.SimulateData.model_validate(data)
        shown = [f"{name} {vals[0]:.3g} to {vals[-1]:.3g} {traj.units.get(name, '')}".strip()
                 for name, vals in list(traj.series.items())[:SERIES_SHOWN] if vals]
        summary = (f"Forked simulation over {horizon_h:g} h with {traj.model_id} "
                   f"v{traj.version}: " + "; ".join(shown) + ".")
        return c.SimulationTrace(
            output_id=traj.output_id, fork_id=traj.fork_id or "", summary=summary,
            assumptions=["The simulation runs on a forked copy of the person's twins; the "
                         "live twins are not changed.",
                         "Model parameters are the AHDT's current estimates for this person.",
                         *assumptions])


def _time(value: Any) -> datetime:
    return value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
