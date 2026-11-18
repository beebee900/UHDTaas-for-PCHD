"""A synthetic diagnostic cohort for the APDT differential models.

Persons come from the WP02 population. Each person's true conditions are drawn independently
from the same priors the network uses, and each finding or test result from the noisy-OR
model of the kb associations. The cohort therefore tests that the models recover the process
that generated it. It is not evidence of clinical accuracy.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from functools import cache

import numpy as np

from apdt.models.context import Observations, Patient
from apdt.models.diagnosis.bn import Network, build_network, prior_for
from synth.population import Person, generate

ASK_RATE = 0.3
TEST_RATE = 0.25
NONE = "none"


@dataclass(frozen=True)
class Case:
    key: str
    patient: Patient
    observations: Observations
    truth: frozenset[str]
    primary: str


@cache
def _prior(condition: str, age: int, sex: str, genotype: str | None) -> float:
    patient = Patient(float(age), sex, hb_genotype=genotype)  # type: ignore[arg-type]
    return prior_for(condition, patient)[0]


def _p_node(node_links: dict[str, float], leak: float, truth: frozenset[str]) -> float:
    log_q = sum(math.log1p(-min(p, 1 - 1e-9)) for c, p in node_links.items() if c in truth)
    return 1.0 - (1.0 - leak) * math.exp(log_q)


def _primary(net: Network, truth: frozenset[str], present: set[str]) -> str:
    best, best_n = NONE, 0
    for c in sorted(truth):
        n = sum(1 for nid in present
                if (node := net.node(nid)) is not None and c in node.links)
        if n > best_n:
            best, best_n = c, n
    return best


def case_for(person: Person, rng: np.random.Generator, net: Network) -> Case | None:
    sex = person.sex
    age = int(person.age_years)
    genotype = person.hb_genotype
    patient = Patient(float(age), sex, hb_genotype=genotype)  # type: ignore[arg-type]
    truth = frozenset(c for c in net.conditions
                      if rng.random() < _prior(c, age, sex, genotype))
    observations = Observations()
    present: set[str] = set()
    for nid, node in net.findings.items():
        if rng.random() >= ASK_RATE:
            continue
        value = bool(rng.random() < _p_node(dict(node.links), node.leak, truth))
        observations.findings[nid] = value
        if value:
            present.add(nid)
    for nid, tnode in net.tests.items():
        if rng.random() >= TEST_RATE:
            continue
        value = bool(rng.random() < _p_node(dict(tnode.links), tnode.leak, truth))
        observations.tests[nid] = value
        if value:
            present.add(nid)
    if not present:
        return None
    return Case(person.hdt_id, patient, observations, truth, _primary(net, truth, present))


def generate_cohort(n: int, seed: int = 11) -> list[Case]:
    """`n` presenting cases (at least one positive finding or test)."""
    net = build_network()
    persons, _ = generate(max(n * 2, 200), seed)
    rng = np.random.default_rng(seed + 101)
    out: list[Case] = []
    for person in persons:
        if person.age_years < 1:
            continue
        case = case_for(person, rng, net)
        if case is not None:
            out.append(case)
        if len(out) == n:
            break
    return out
