"""Test selection by value of information (design 05, 5.5.1).

VoI of a test is the expected reduction in the summed binary entropy of the candidate
conditions' posterior probabilities. The ranking score is VoI divided by a weighted sum of
the test's price and turnaround from the tenant price list (`kb/prices/<tenant>.csv`).
"""

from __future__ import annotations

import csv
import math
from dataclasses import dataclass
from functools import lru_cache

from apdt.models.context import Observations, Patient, kb, param
from apdt.models.diagnosis.bn import DifferentialModel, Enumerator, Evidence
from atra.config import get_settings


@dataclass(frozen=True)
class Offer:
    test_id: str
    price_ngn: float
    turnaround_h: float
    on_site: bool


@dataclass(frozen=True)
class Ranked:
    test_id: str
    name: str
    voi: float
    cost_ngn: float
    turnaround_h: float
    on_site: bool
    score: float
    p_positive: float
    top_if_positive: str
    top_if_negative: str
    assumed_accuracy: bool


@dataclass(frozen=True)
class MindChange:
    test_id: str
    result: bool
    new_top: str
    new_probability: float
    voi: float


@lru_cache(maxsize=8)
def price_list(tenant_id: str) -> dict[str, Offer]:
    path = get_settings().kb_dir / "prices" / f"{tenant_id}.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8") as fh:
        return {r["test"]: Offer(r["test"], float(r["price_ngn"]), float(r["turnaround_h"]),
                                     r["on_site"] == "True")
                for r in csv.DictReader(fh)}


def _entropy(ps: list[float]) -> float:
    total = 0.0
    for p in ps:
        if 0.0 < p < 1.0:
            total -= p * math.log(p) + (1.0 - p) * math.log1p(-p)
    return total


def _top(marginals: dict[str, float], cands: list[str]) -> str:
    return max(cands, key=lambda c: marginals[c])


def rank_tests(model: DifferentialModel, patient: Patient, obs: Observations
               ) -> tuple[list[Ranked], list[MindChange]]:
    """Tests ranked by score, and the outcomes that would change the top diagnosis."""
    diff = model.differential(patient, obs)
    cands = [c.condition for c in diff.candidates]
    if not cands:
        return [], []
    pri = {c: v[0] for c, v in model.priors(patient).items()}
    evidence = Evidence.of(obs, model.net)
    offers = price_list(patient.tenant_id)
    w = param("voi_weights")
    top_now = cands[0]
    scores: list[Ranked] = []
    changes: list[MindChange] = []
    for tid, node in model.net.tests.items():
        if tid in evidence.values or tid not in offers or not set(node.links) & set(cands):
            continue
        enum = Enumerator(model.net, pri, evidence, also=[tid])
        before = model.mixture(enum)
        marg0 = enum.marginals(before)
        h0 = _entropy([marg0[c] for c in cands if c in marg0])
        like = {True: enum.node_probability(tid, True), False: enum.node_probability(tid, False)}
        p_pos = float((before * like[True]).sum())
        h_after = 0.0
        tops: dict[bool, str] = {}
        for outcome in (True, False):
            p_out = p_pos if outcome else 1.0 - p_pos
            if p_out <= 0.0:
                tops[outcome] = top_now
                continue
            post = model.mixture(enum, like[outcome])
            marg = enum.marginals(post)
            h_after += p_out * _entropy([marg[c] for c in cands if c in marg])
            tops[outcome] = _top({**{c: 0.0 for c in cands}, **marg}, cands)
            if tops[outcome] != top_now:
                changes.append(MindChange(tid, outcome, tops[outcome], marg[tops[outcome]],
                                          h0 - h_after))
        voi = max(h0 - h_after, 0.0)
        offer = offers[tid]
        cost = (float(w["cost"]) * offer.price_ngn / float(w["cost_unit_ngn"])
                + float(w["delay"]) * offer.turnaround_h / float(w["delay_unit_h"]))
        scores.append(Ranked(tid, str(kb().entry(tid).content()["name"]), voi,
                                offer.price_ngn, offer.turnaround_h, offer.on_site,
                                voi / cost if cost > 0 else 0.0, p_pos, tops[True],
                                tops[False], node.assumed_accuracy))
    scores.sort(key=lambda s: -s.score)
    by_voi = {s.test_id: s.voi for s in scores}
    changes = [MindChange(c.test_id, c.result, c.new_top, c.new_probability,
                          by_voi.get(c.test_id, c.voi)) for c in changes]
    changes.sort(key=lambda c: -c.voi)
    return scores, changes

