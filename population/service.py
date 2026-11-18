"""Population tool handlers and the reply side of the Prior and Norms connectors (design 03,
3.15 and 3.16)."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from ahdt.coupling.base import QueryFn
from atra.kb import KnowledgeBase
from atra.service import Identity, Problem, ToolHandler, meta
from population.cohort import CohortStore
from population.federated import PrivacyLedger
from population.priors import MODEL_ID, PopulationPriors, UnknownCondition, UnknownNorm


@dataclass
class PopulationService:
    priors: PopulationPriors
    cohort: CohortStore
    ledger: PrivacyLedger
    kb: KnowledgeBase

    def _meta(self) -> dict[str, Any]:
        return meta((MODEL_ID, self.priors.version), federated_rounds=self.priors.rounds)

    async def tool_priors(self, args: BaseModel, ident: Identity) -> dict[str, Any]:
        a: Any = args
        try:
            rows = [self.priors.prior(cond, a.age_band, a.sex, a.season, a.region).row()
                    for cond in a.conditions]
        except UnknownCondition as exc:
            raise Problem(404, "not-found", f"no prior for condition {exc.args[0]}") from exc
        except ValueError as exc:
            raise Problem(422, "invalid-arguments", str(exc)) from exc
        return {"priors": rows, "_meta": self._meta()}

    async def tool_norms(self, args: BaseModel, ident: Identity) -> dict[str, Any]:
        a: Any = args
        try:
            rows = [self.priors.norm(f, a.age_band, a.sex) for f in a.fields]
        except UnknownNorm as exc:
            raise Problem(404, "not-found", f"no norm for field {exc.args[0]} in "
                                            f"{a.age_band} {a.sex}") from exc
        except ValueError as exc:
            raise Problem(422, "invalid-arguments", str(exc)) from exc
        return {"norms": rows, "_meta": self._meta()}

    async def tool_contribute(self, args: BaseModel, ident: Identity) -> dict[str, Any]:
        a: Any = args
        try:
            receipt = await asyncio.to_thread(self.cohort.contribute, a.contract, a.records)
        except ValueError as exc:
            raise Problem(422, "invalid-arguments", str(exc)) from exc
        return {"accepted": receipt.accepted, "suppressed": receipt.suppressed, "k": receipt.k}

    def handlers(self) -> dict[str, ToolHandler]:
        return {"population.priors": self.tool_priors, "population.norms": self.tool_norms,
                "population.contribute": self.tool_contribute}

    async def _prior_reply(self, query: Mapping[str, Any]) -> dict[str, Any]:
        prior = self.priors.prior(str(query["condition"]), str(query["age_band"]),
                                  str(query["sex"]), str(query["season"]),
                                  str(query["region"]))
        row = prior.row()
        row.pop("source")
        return {"context": row}

    async def _norm_reply(self, query: Mapping[str, Any]) -> dict[str, Any]:
        norm = self.priors.norm(str(query["field"]), str(query["age_band"]), str(query["sex"]))
        return {"context": {k: norm[k] for k in ("field", "p05", "p50", "p95")}}

    def query_providers(self) -> dict[str, QueryFn]:
        """Answers for `build_coupling(..., query_providers=...)`: the Population twin's side
        of the request-reply PriorConnector and NormsConnector."""
        return {"PriorConnector": self._prior_reply, "NormsConnector": self._norm_reply}
