"""Model lifecycle: drift monitoring and stage promotion (design 04, 4.7.3).

`DriftMonitor` compares each numeric output of a model over the last 7 days with the 7 days
before. A population stability index above `PSI_LIMIT`, or a two-sample Kolmogorov-Smirnov
test below `KS_ALPHA`, counts as drift and publishes `model.drift_detected` for the
model-lifecycle agent. Both limits are the conventional ones for these statistics, not
clinical values.

The routes list registry entries with their stage and move a version between stages:
`None` to `Staging` by an administrator or the clinical safety officer, `Staging` to
`Production` by the clinical safety officer only. A rollback re-promotes the newest
archived version.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import numpy as np
from fastapi import FastAPI, Request
from pydantic import BaseModel
from scipy.stats import ks_2samp

from ahdt.services.runtime import Runtime
from atra.contracts import EventEnvelope, Role
from atra.ids import new_record_id
from atra.service import Problem, authenticate, verifier_of

WINDOW = timedelta(days=7)
PSI_LIMIT = 0.2
KS_ALPHA = 0.05
BINS = 10
MIN_SAMPLES = 8
EPS = 1e-4
PROMOTE_ROLES = {"Staging": {Role.ADMINISTRATOR, Role.CLINICAL_SAFETY_OFFICER},
                 "Production": {Role.CLINICAL_SAFETY_OFFICER},
                 "Archived": {Role.CLINICAL_SAFETY_OFFICER}}
VIEW_ROLES = {Role.ADMINISTRATOR, Role.CLINICAL_SAFETY_OFFICER, Role.MEDICAL_OFFICER}


def psi(reference: Sequence[float], current: Sequence[float], bins: int = BINS) -> float:
    """Population stability index of `current` against `reference` on reference deciles."""
    ref = np.asarray(reference, dtype=float)
    cur = np.asarray(current, dtype=float)
    edges = np.unique(np.quantile(ref, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    p = np.histogram(ref, edges)[0] / len(ref)
    q = np.histogram(cur, edges)[0] / len(cur)
    p, q = np.clip(p, EPS, None), np.clip(q, EPS, None)
    return float(np.sum((q - p) * np.log(q / p)))


@dataclass(frozen=True)
class Drift:
    output: str
    psi: float
    ks_p: float

    @property
    def drifted(self) -> bool:
        return self.psi > PSI_LIMIT or self.ks_p < KS_ALPHA


class DriftMonitor:
    def __init__(self, runtime: Runtime) -> None:
        self.rt = runtime

    async def report(self, model_id: str, *, now: datetime | None = None) -> list[Drift]:
        pipe = await self.rt.pipeline()
        now = now or datetime.now(UTC)
        rows = pipe.lake.query(
            "SELECT body, ingested_at FROM outputs WHERE model_id = ? AND ingested_at >= ?",
            [model_id, now - 2 * WINDOW], table="outputs")
        recent: dict[str, list[float]] = {}
        before: dict[str, list[float]] = {}
        for row in rows:
            bucket = recent if row["ingested_at"] >= now - WINDOW else before
            for name, value in json.loads(row["body"]).get("values", {}).items():
                if isinstance(value, int | float) and not isinstance(value, bool):
                    bucket.setdefault(name, []).append(float(value))
        out = []
        for name, ref in before.items():
            cur = recent.get(name, [])
            if len(ref) < MIN_SAMPLES or len(cur) < MIN_SAMPLES:
                continue
            out.append(Drift(name, psi(ref, cur), float(ks_2samp(ref, cur).pvalue)))
        return out

    async def check(self, model_id: str, *, now: datetime | None = None) -> list[Drift]:
        """The drifted outputs; publishes `model.drift_detected` when there are any."""
        drifted = [d for d in await self.report(model_id, now=now) if d.drifted]
        if drifted:
            await self.rt.backends.events.publish(EventEnvelope(
                event_id=new_record_id(), event_type="model.drift_detected",
                source="ahdt.lifecycle", wall_time=now or datetime.now(UTC), sim_time=None,
                trace_id=new_record_id(),
                payload={"model_id": model_id,
                         "outputs": [{"output": d.output, "psi": d.psi, "ks_p": d.ks_p}
                                     for d in drifted]}))
        return drifted


class StageChange(BaseModel):
    stage: str


def mount_lifecycle(app: FastAPI, runtime: Runtime) -> None:
    registry = runtime.backends.models

    async def who(request: Request) -> Any:
        return await authenticate(request.headers, await verifier_of(app))

    async def sync() -> None:
        """Register every catalogue model that the registry does not hold yet."""
        from ahdt.models.catalogue import register_all

        if not await registry.list():
            await register_all(registry, runtime.catalogue)

    @app.get("/v1/models", tags=["lifecycle"], summary="Registered models with their stage")
    async def models(request: Request, twin: str | None = None) -> list[dict[str, Any]]:
        ident = await who(request)
        if ident.ctx.actor_role not in VIEW_ROLES:
            raise Problem(403, "forbidden", "this role may not list models")
        await sync()
        return [{"model_id": e.model_id, "version": e.version, "twin": str(e.twin),
                 "tier": e.tier.value, "stage": await registry.stage(e.model_id, e.version)}
                for e in await registry.list(twin=twin)]

    @app.post("/v1/models/{model_id}/versions/{version}/stage", tags=["lifecycle"],
              summary="Move a model version to Staging, Production or Archived")
    async def stage(model_id: str, version: str, change: StageChange, request: Request
                    ) -> dict[str, str]:
        ident = await who(request)
        await sync()
        allowed = PROMOTE_ROLES.get(change.stage)
        if allowed is None:
            raise Problem(422, "invalid-arguments", f"unknown stage {change.stage}")
        if ident.ctx.actor_role not in allowed:
            raise Problem(403, "forbidden", f"this role may not move a model to {change.stage}")
        try:
            current = await registry.stage(model_id, version)
        except KeyError:
            raise Problem(404, "not-found", f"no model {model_id} {version}") from None
        order = {"None": 0, "Staging": 1, "Production": 2, "Archived": 3}
        if change.stage == "Production" and current != "Staging":
            raise Problem(409, "conflict", "only a Staging version moves to Production")
        if order[change.stage] <= order[current] and change.stage != "Production":
            raise Problem(409, "conflict", f"{current} cannot move to {change.stage}")
        await registry.transition(model_id, version, change.stage,  # type: ignore[arg-type]
                                  by=ident.ctx.actor_id)
        app.state.audit.append(
            actor={"id": ident.ctx.actor_id, "role": ident.ctx.actor_role.value},
            action="model.stage", target=f"{model_id}@{version}", purpose="operations",
            outcome="ok", reason=f"{current} to {change.stage}")
        return {"model_id": model_id, "version": version, "stage": change.stage}

    @app.post("/v1/models/{model_id}/rollback", tags=["lifecycle"],
              summary="Re-promote the newest archived version")
    async def rollback(model_id: str, request: Request) -> dict[str, str]:
        ident = await who(request)
        if ident.ctx.actor_role not in PROMOTE_ROLES["Production"]:
            raise Problem(403, "forbidden", "this role may not roll a model back")
        await sync()
        versions = [e.version for e in await registry.list() if e.model_id == model_id]
        archived = [v for v in versions if await registry.stage(model_id, v) == "Archived"]
        if not archived:
            raise Problem(409, "conflict", f"{model_id} has no archived version")
        previous = max(archived, key=_semver)
        await registry.transition(model_id, previous, "Production", by=ident.ctx.actor_id)
        app.state.audit.append(
            actor={"id": ident.ctx.actor_id, "role": ident.ctx.actor_role.value},
            action="model.rollback", target=f"{model_id}@{previous}", purpose="operations",
            outcome="ok")
        return {"model_id": model_id, "version": previous, "stage": "Production"}


def _semver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split(".") if x.isdigit())


__all__ = ["Drift", "DriftMonitor", "mount_lifecycle", "psi"]
