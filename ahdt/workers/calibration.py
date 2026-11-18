"""Nightly re-calibration of the organ models (design 04, 4.7.3).

The workflow calibrates every model of each person that has new observations, then sleeps a
day. It writes through the instance store as the assimilation service. The p0 profile runs it
on the in-process workflow engine and p1 on Temporal with the same function.
"""

from __future__ import annotations

from typing import Any

from ahdt.services import Services
from atra.backends.base import WorkflowBackend, WorkflowContext

WORKFLOW = "nightly_calibration"
DAY_H = 24.0


def register(workflows: WorkflowBackend, services: Services) -> None:
    async def calibrate_person(hdt_id: str) -> list[dict[str, Any]]:
        return await services.model.calibrate_all(hdt_id)

    async def nightly_calibration(ctx: WorkflowContext, hdt_ids: list[str],
                                  interval_h: float = DAY_H, rounds: int | None = None
                                  ) -> int:
        done = 0
        while rounds is None or done < rounds:
            for hdt_id in hdt_ids:
                await ctx.activity(calibrate_person, hdt_id)
            done += 1
            await ctx.sleep(interval_h * 3600.0)
        return done

    workflows.register(WORKFLOW, nightly_calibration)


async def start(workflows: WorkflowBackend, hdt_ids: list[str], *, interval_h: float = DAY_H,
                rounds: int | None = None) -> str:
    return await workflows.start(WORKFLOW, {"hdt_ids": hdt_ids, "interval_h": interval_h,
                                            "rounds": rounds})
