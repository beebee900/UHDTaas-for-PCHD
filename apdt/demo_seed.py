"""Open one episode for each demo persona and load their readings.

    python -m apdt.demo_seed [--profile p0]

Each persona gets an episode at the APDT with the findings, results and measurements of the
persona's scenario (`evaluation.models.apdt.scenarios`), and the scenario's vital readings go to
the AHDT as a 24 hour demo series (the scenario value with a fixed swing of 0.3 units). The APDT
then runs the reasoner, so every worklist is full. A persona that already has an open episode is
skipped. The command needs the services of `python run.py` and the local issuer (profile p0).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from apdt.services.inputs import to_resources
from atra.backends import Backends
from atra.config import Settings, get_settings
from atra.contracts import Role
from atra.personas import BY_KEY, PERSONAS, Persona
from atra.security import LocalIssuer
from evaluation.models.apdt.scenarios import BY_SCENARIO

# Scenario measurement -> (LOINC code, unit) for the readings that the AHDT stores.
AHDT_READINGS = {"temperature": ("8310-5", "Cel"), "sbp": ("8480-6", "mm[Hg]"),
                 "dbp": ("8462-4", "mm[Hg]"), "hb": ("718-7", "g/dL")}
SERIES_HOURS = 24
SWING = (0.0, 0.3, -0.3, 0.15)


def readings_csv(persona: Persona, now: datetime) -> str | None:
    measurements = BY_SCENARIO[persona.key].observations.measurements
    rows = ["record_id,hdt_id,code_system,code,value,unit,effective_time"]
    for name, (loinc, unit) in AHDT_READINGS.items():
        if name not in measurements:
            continue
        for i in range(SERIES_HOURS):
            at = now - timedelta(hours=SERIES_HOURS - 1 - i)
            value = measurements[name] + (SWING[i % len(SWING)] if i < SERIES_HOURS - 1 else 0.0)
            rows.append(f"seed-{persona.key}-{loinc}-{i},{persona.hdt_id},loinc,{loinc},"
                        f"{value:.2f},{unit},{at.replace(tzinfo=None).isoformat()}")
    return "\n".join(rows) + "\n" if len(rows) > 1 else None


async def seed(apdt: httpx.AsyncClient, ahdt: httpx.AsyncClient | None, issuer: LocalIssuer,
               personas: Sequence[Persona] = PERSONAS) -> list[dict[str, Any]]:
    """Seed `personas` through the services' HTTP APIs; returns one summary per persona."""
    now = datetime.now(UTC)
    out: list[dict[str, Any]] = []
    for persona in personas:
        tenant = persona.tenant_id
        mo = {"Authorization": "Bearer " + issuer.issue(
            f"medical_officer.{tenant}", Role.MEDICAL_OFFICER, tenant_id=tenant)}
        base = f"/v1/t/{tenant}"
        queue = (await apdt.get(f"{base}/worklists/medical_officer", headers=mo)).json()
        if any(i.get("hdt_id") == persona.hdt_id for i in queue["items"]):
            out.append({"persona": persona.key, "skipped": "open episode exists"})
            continue
        csv = readings_csv(persona, now)
        if ahdt is not None and csv is not None:
            svc = {"Authorization": "Bearer " + issuer.issue_service("apdt-demo-seed")}
            r = await ahdt.post("/v1/import?format=csv", content=csv, headers=svc)
            r.raise_for_status()
        scenario = BY_SCENARIO[persona.key]
        r = await apdt.post(f"{base}/episodes", headers=mo, json={
            "hdt_id": persona.hdt_id, "reason": persona.scenario.capitalize()})
        r.raise_for_status()
        eid = r.json()["episode"]["episode_id"]
        for resource in to_resources(scenario.patient, scenario.observations):
            (await apdt.post(f"{base}/episodes/{eid}/resources", headers=mo,
                             json=resource)).raise_for_status()
        recs = await apdt.get(f"{base}/episodes/{eid}/recommendations", headers=mo)
        recs.raise_for_status()
        out.append({"persona": persona.key, "episode_id": eid,
                    "recommendations": [x["kind"] for x in recs.json()]})
    return out


async def run(settings: Settings, personas: Sequence[Persona]) -> list[dict[str, Any]]:
    issuer = Backends(settings, "apdt-demo-seed").issuer
    async with httpx.AsyncClient(base_url=settings.services.apdt, timeout=120) as apdt, \
            httpx.AsyncClient(base_url=settings.services.ahdt, timeout=60) as ahdt:
        return await seed(apdt, ahdt, issuer, personas)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Open an episode for each demo persona.")
    parser.add_argument("--persona", action="append", choices=sorted(BY_KEY),
                        help="seed only this persona (repeatable)")
    args = parser.parse_args(argv)
    settings = get_settings()
    if settings.backend.identity != "memory":
        print("the demo seed needs the local issuer (profile p0)", file=sys.stderr)
        return 1
    chosen = [BY_KEY[k] for k in args.persona] if args.persona else list(PERSONAS)
    for line in asyncio.run(run(settings, chosen)):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
