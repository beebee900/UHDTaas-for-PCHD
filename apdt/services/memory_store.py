"""Episodes, their FHIR resources, recommendations, bundles and decisions, in process memory."""

from __future__ import annotations

import itertools
import threading
from datetime import UTC, datetime
from typing import Any

from atra import contracts as c
from atra.ids import episode_id, uuid7


def episode_of_care(ep: c.Episode) -> dict[str, Any]:
    return {"resourceType": "EpisodeOfCare", "id": ep.episode_id,
            "status": "active" if ep.status == "open" else "finished",
            "patient": {"reference": f"Patient/{ep.hdt_id}"},
            "managingOrganization": {"reference": f"Organization/{ep.tenant_id}"},
            "period": {"start": ep.opened_at.isoformat(),
                       **({"end": ep.closed_at.isoformat()} if ep.closed_at else {})}}


class InMemoryEpisodeStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._numbers = itertools.count(1)
        self.episodes: dict[str, c.Episode] = {}
        self.resources: dict[str, list[dict[str, Any]]] = {}
        self.recommendations: dict[str, list[c.Recommendation]] = {}
        self.bundles: dict[str, c.ExplanationBundle] = {}
        self.input_keys: dict[str, str] = {}
        self.decisions: dict[str, list[c.ClinicalDecision]] = {}
        self._rec_numbers: dict[str, int] = {}

    def create(self, tenant_id: str, body: c.EpisodeCreate, clinician: str) -> c.Episode:
        with self._lock:
            ep = c.Episode(episode_id=episode_id(datetime.now(UTC).year, next(self._numbers)),
                           tenant_id=tenant_id, hdt_id=body.hdt_id, status="open",
                           opened_at=datetime.now(UTC), reason=body.reason,
                           responsible_clinician=body.responsible_clinician or clinician)
            self.episodes[ep.episode_id] = ep
            self.resources[ep.episode_id] = []
            self.recommendations[ep.episode_id] = []
            return ep

    def get(self, tenant_id: str, eid: str) -> c.Episode:
        ep = self.episodes.get(eid)
        if ep is None or ep.tenant_id != tenant_id:
            raise KeyError(eid)
        return ep

    def open_episodes(self, tenant_id: str) -> list[c.Episode]:
        return self.list(tenant_id, "open")

    def list(self, tenant_id: str, status: str = "all") -> list[c.Episode]:
        """The tenant's episodes with `status` (`open`, `closed` or `all`), newest first."""
        found = [e for e in self.episodes.values()
                 if e.tenant_id == tenant_id and status in ("all", e.status)]
        return sorted(found, key=lambda e: e.opened_at, reverse=True)

    def close(self, tenant_id: str, eid: str) -> c.Episode:
        with self._lock:
            ep = self.get(tenant_id, eid).model_copy(
                update={"status": "closed", "closed_at": datetime.now(UTC)})
            self.episodes[eid] = ep
            return ep

    def add_resource(self, tenant_id: str, eid: str, resource: dict[str, Any]) -> dict[str, Any]:
        self.get(tenant_id, eid)
        stored = {**resource, "id": resource.get("id") or uuid7().hex}
        with self._lock:
            self.resources[eid].append(stored)
        return stored

    def next_number(self, eid: str) -> int:
        with self._lock:
            self._rec_numbers[eid] = self._rec_numbers.get(eid, 0) + 1
            return self._rec_numbers[eid]

    def recommendation(self, recommendation_id: str) -> c.Recommendation:
        for recs in self.recommendations.values():
            for rec in recs:
                if rec.recommendation_id == recommendation_id:
                    return rec
        raise KeyError(recommendation_id)

    def replace_recommendation(self, rec: c.Recommendation) -> None:
        with self._lock:
            recs = self.recommendations[rec.episode_id or ""]
            recs[:] = [rec if r.recommendation_id == rec.recommendation_id else r for r in recs]
