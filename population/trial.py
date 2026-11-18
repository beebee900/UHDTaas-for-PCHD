"""In-silico trial engine (design 04, 4.5.3: in-silico trial).

A virtual cohort is sampled from the twin parameter distributions: each virtual twin gets
individual values of the heart model's calibratable parameters (`personalise`, log-normal
around the published values) and a systemic resistance factor from `trial.params.yaml`.
Each twin has its own heart instance in an instance store. The control arm is the twin's
own instance; the treatment scenario runs on a fork of that instance (design 03, 3.5), so
the twin itself never changes, and the fork is released afterwards. The summary compares the
arms on systolic pressure and on the share of twins below the kb hypertension threshold.
"""

from __future__ import annotations

import asyncio
import hashlib
import math
from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from scipy import stats

from ahdt.models.cardiovascular.heart import HeartModel
from ahdt.models.modes import person_seed, personalise
from ahdt.models.organs.store import InstanceStore
from ahdt.models.params import ParamSet, load_params
from atra import contracts as c
from atra.config import get_settings
from atra.connectors import DTKind
from atra.ids import instance_id
from atra.kb import KnowledgeBase

PARAMS = Path(__file__).with_name("trial.params.yaml")
MODEL_ID = "ahdt.population.in_silico_trial"
HEART = "UBERON:0000948"


@lru_cache(maxsize=1)
def params() -> ParamSet:
    return load_params(PARAMS)


def virtual_id(seed: int, index: int) -> str:
    return "hdt-" + hashlib.sha256(f"trial|{seed}|{index}".encode()).hexdigest()[:12]


@dataclass(frozen=True)
class TwinOutcome:
    hdt_id: str
    fork_id: str
    resistance_factor: float
    control_sbp: float
    treated_sbp: float


@dataclass(frozen=True)
class TrialResult:
    outcomes: list[TwinOutcome]
    threshold_sbp: float
    reduction: float

    def summary(self) -> dict[str, Any]:
        control = np.array([o.control_sbp for o in self.outcomes])
        treated = np.array([o.treated_sbp for o in self.outcomes])
        diff = treated - control
        n = len(diff)
        half = float(stats.t.ppf(0.975, n - 1) * diff.std(ddof=1) / math.sqrt(n)) if n > 1 else 0.0
        return {
            "model": MODEL_ID, "subjects": n, "design": "paired: control instance, treated fork",
            "outcome": "systolic blood pressure (mm[Hg])",
            "control_mean_sbp": float(control.mean()), "treated_mean_sbp": float(treated.mean()),
            "mean_difference": float(diff.mean()),
            "mean_difference_95ci": [float(diff.mean()) - half, float(diff.mean()) + half],
            "controlled_share_control": float((control < self.threshold_sbp).mean()),
            "controlled_share_treated": float((treated < self.threshold_sbp).mean()),
            "responder_share_10mmhg": float((diff <= -10.0).mean()),
            "threshold_sbp": self.threshold_sbp,
            "treatment_resistance_reduction": self.reduction,
            "forks_released": len({o.fork_id for o in self.outcomes}),
        }


class InSilicoTrial:
    def __init__(self, store: InstanceStore | None = None, model: HeartModel | None = None,
                 kb: KnowledgeBase | None = None) -> None:
        self.store = store or InstanceStore()
        self.model = model or HeartModel()
        kb = kb or KnowledgeBase(get_settings().kb_dir)
        self.threshold = float(kb.lookup("threshold.hypertension", "systolic_at_or_above"))
        self.p = params().values

    async def _enrol(self, hdt_id: str, rf: float) -> c.InstanceRecord:
        individual = personalise(self.model, person_seed(hdt_id, self.model.model_id))
        p = {**self.model.parameters(), **individual}
        state = self.model.initial_state(p, {})
        values = await asyncio.to_thread(self.model.evaluate, p, state, {"resistance_factor": rf})
        record = c.InstanceRecord(
            instance_id=instance_id(hdt_id, HEART), anatomy=HEART, model_id=self.model.model_id,
            version=self.model.version, owner_dt=DTKind.CARDIOVASCULAR, params=individual,
            state={**state, **values, "resistance_factor": rf})
        return await self.store.create(record)

    async def _treat(self, hdt_id: str, rf: float) -> tuple[str, float]:
        fork = await self.store.fork(hdt_id, [HEART])
        try:
            record = await fork.get(hdt_id, HEART)
            scenario = c.Scenario(kind="intervention", dts=[DTKind.CARDIOVASCULAR],
                                  intervention={"resistance_factor": rf * (
                                      1.0 - self.p["treatment_resistance_reduction"])})
            run = await self.model.simulate(record, scenario, 0.0, 1.0, fork_id=fork.fork_id)
            sbp = run.series["sbp"][-1]
            await fork.write(hdt_id, HEART, writer=DTKind.CARDIOVASCULAR, state={"sbp": sbp},
                             params=None, expected_revision=record.revision)
            return fork.fork_id, sbp
        finally:
            await self.store.release(fork.fork_id)

    async def run(self, subjects: int = 100, seed: int = 0) -> TrialResult:
        rng = np.random.default_rng(seed)
        rfs: Sequence[float] = rng.normal(self.p["resistance_factor_mean"],
                                          self.p["resistance_factor_sd"], subjects).tolist()
        outcomes = []
        for i, rf in enumerate(rfs):
            hdt_id = virtual_id(seed, i)
            record = await self._enrol(hdt_id, float(rf))
            fork_id, treated = await self._treat(hdt_id, float(rf))
            control = (await self.store.get(hdt_id, HEART)).state["sbp"]
            if control != record.state["sbp"]:
                raise RuntimeError(f"the treatment fork changed {hdt_id}")
            outcomes.append(TwinOutcome(hdt_id, fork_id, float(rf), float(control), treated))
        return TrialResult(outcomes, self.threshold,
                           self.p["treatment_resistance_reduction"])
