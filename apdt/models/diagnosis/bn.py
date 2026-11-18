"""Differential diagnosis: a noisy-OR Bayesian network built from the kb (design 05, 5.5.1).

One binary node per condition. A finding or test result is a noisy-OR child of the conditions
the kb associates with it: P(finding | condition) is `assoc.strength_probability` for the
association strength, and a test's links come from its kb sensitivity and specificity. Priors
come from the Population twin (kb seeds or the trained table), then a hard gate sets a
condition to probability 0 when the patient cannot have it.

Three structure variants differ in which condition combinations are allowed: `independent`
(co-morbidity allowed), `grouped` (one condition per kb pathway, co-morbidity across
pathways) and `exclusive` (one condition at a time). Bayesian model averaging combines them
with weights fitted by BIC on the synthetic validation split.

Inference is exact. `Enumerator` sums over condition subsets with numpy; `pgmpy_posterior`
builds the same network in pgmpy and runs variable elimination. Tests compare the two.
"""

from __future__ import annotations

import itertools
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from apdt.models.context import HERE, Observations, Patient, kb, param
from population.priors import PopulationPriors, UnknownCondition

VARIANTS = ("independent", "grouped", "exclusive")
MAX_RELEVANT = 16
MAX_PGMPY_CONSTRAINT = 14
WEIGHTS_FILE = HERE / "diagnosis" / "bma_weights.json"
EPS = 1e-9

type Vec = NDArray[np.float64]


@dataclass(frozen=True)
class Node:
    """A noisy-OR child: `links` maps a condition to its activation probability."""

    node_id: str
    leak: float
    links: Mapping[str, float]
    assumed_accuracy: bool = False


@dataclass(frozen=True)
class Network:
    conditions: tuple[str, ...]
    groups: Mapping[str, str]
    findings: Mapping[str, Node]
    tests: Mapping[str, Node]

    def node(self, node_id: str) -> Node | None:
        return self.findings.get(node_id) or self.tests.get(node_id)


def _percent(value: Any) -> float:
    return float(value) / 100.0


def _test_node(test_id: str, content: Mapping[str, Any]) -> Node | None:
    sens: dict[str, float] = {}
    spec: dict[str, float] = {}
    assumed = False
    for t in content.get("targets", []):
        s = t.get("sensitivity_percent", t.get("sensitivity_percent_at_least"))
        f = t.get("specificity_percent", t.get("specificity_percent_at_least"))
        if s is None or f is None:
            continue
        assumed = assumed or "sensitivity_percent_at_least" in t or \
            "specificity_percent_at_least" in t
        sens[t["condition"]] = _percent(s)
        spec[t["condition"]] = _percent(f)
    if not sens:
        return None
    leak = 1.0 - min(spec.values())
    links = {c: min(1.0 - EPS, max(0.0, 1.0 - (1.0 - s) / (1.0 - leak)))
             for c, s in sens.items()}
    return Node(test_id, leak, links, assumed)


@lru_cache(maxsize=1)
def build_network() -> Network:
    """The noisy-OR network of every kb association and every test with an accuracy."""
    k = kb()
    strength = k.resolve("assoc.strength_probability")
    leak = float(strength["leak"])
    finding_links: dict[str, dict[str, float]] = {}
    for entry_id in k.ids():
        if not entry_id.startswith("assoc."):
            continue
        content = k.entry(entry_id).content()
        if "condition" not in content:
            continue
        for f in content["findings"]:
            p = float(strength[f["strength"]])
            cur = finding_links.setdefault(f["finding"], {})
            cur[content["condition"]] = max(cur.get(content["condition"], 0.0), p)
    for extra in param("extra_links"):
        p = float(strength[extra["strength"]])
        finding_links.setdefault(extra["finding"], {})[extra["condition"]] = p
    findings = {fid: Node(fid, leak, links) for fid, links in finding_links.items()}
    tests = {}
    for entry_id in k.ids():
        if entry_id.startswith("test."):
            node = _test_node(entry_id, k.entry(entry_id).content())
            if node is not None:
                tests[entry_id] = node
    conditions = tuple(i for i in k.ids() if i.startswith("cond."))
    groups = {c: str(k.entry(c).content().get("pathway", c)) for c in conditions}
    return Network(conditions, groups, findings, tests)


@lru_cache(maxsize=1)
def _priors() -> PopulationPriors:
    return PopulationPriors.load(kb())


def gate_open(condition: str, p: Patient) -> bool:
    gate = param("hard_gates").get(condition)
    if gate is None:
        return True
    for key, allowed in gate.items():
        value = {"hb_genotype": p.hb_genotype, "sex": p.sex, "pregnancy": p.pregnancy}[key]
        if value not in allowed:
            return False
    return True


def prior_for(condition: str, p: Patient) -> tuple[float, str]:
    """(probability, source) for a condition and patient."""
    if not gate_open(condition, p):
        return 0.0, "gate"
    try:
        pr = _priors().prior(condition, str(int(p.age_years)), p.sex, p.season, p.region)
    except UnknownCondition:
        return float(param("default_prior")), "assumption:default_prior"
    return pr.prevalence, pr.source


@dataclass(frozen=True)
class Evidence:
    """Observed nodes: node id → value (present or positive is True)."""

    values: Mapping[str, bool]

    @classmethod
    def of(cls, obs: Observations, net: Network | None = None) -> Evidence:
        net = net or build_network()
        values = {f: v for f, v in obs.findings.items() if f in net.findings}
        values.update({t: v for t, v in obs.tests.items() if t in net.tests})
        return cls(values)


def _doubling(weights: Sequence[float]) -> Vec:
    """For every subset (bit j = j-th item) the sum of the items' weights."""
    out: Vec = np.zeros(1)
    for w in weights:
        out = np.concatenate([out, out + w])
    return out


def _logit(p: float) -> float:
    if p <= 0.0:
        return -math.inf
    p = min(p, 1.0 - EPS)
    return math.log(p) - math.log1p(-p)


class Enumerator:
    """Exact inference over the conditions that the evidence touches. When more than `limit`
    conditions are touched, the unsupported ones with the lowest priors are fixed absent and
    listed in `dropped`; the result is then approximate."""

    def __init__(self, net: Network, priors: Mapping[str, float], evidence: Evidence,
                 also: Sequence[str] = (), limit: int = MAX_RELEVANT) -> None:
        self.net = net
        self.evidence = evidence
        touched = {c for nid in (*evidence.values, *also)
                   if (node := net.node(nid)) is not None for c in node.links}
        supported = {c for nid, v in evidence.values.items() if v
                     and (node := net.node(nid)) is not None for c in node.links}
        order = sorted((c for c in net.conditions if c in touched),
                       key=lambda c: (c not in supported, -priors[c]))
        if len([c for c in order if c in supported]) > limit:
            raise ValueError(f"more than {limit} conditions are supported by the evidence")
        kept = set(order[:limit])
        self.relevant = tuple(c for c in net.conditions if c in kept)
        self.dropped = tuple(c for c in order if c not in kept)
        self.priors = {c: priors[c] for c in self.relevant}
        r = len(self.relevant)
        base = sum(math.log1p(-min(p, 1.0 - EPS)) for p in self.priors.values())
        with np.errstate(invalid="ignore"):
            self._prior = np.exp(base + _doubling([_logit(self.priors[c])
                                                   for c in self.relevant]))
        self._prior = np.nan_to_num(self._prior, nan=0.0)
        self._likelihood = np.ones(2 ** r)
        for nid, value in evidence.values.items():
            self._likelihood *= self.node_probability(nid, value)

    def node_probability(self, node_id: str, value: bool) -> Vec:
        """P(node = value | state) for every subset state."""
        node = self.net.node(node_id)
        assert node is not None
        logs = [math.log1p(-min(node.links.get(c, 0.0), 1.0 - EPS)) for c in self.relevant]
        p1 = 1.0 - (1.0 - node.leak) * np.exp(_doubling(logs))
        return p1 if value else 1.0 - p1

    def allowed(self, variant: str) -> NDArray[np.bool_]:
        n = len(self.relevant)
        if variant == "independent":
            return np.ones(2 ** n, dtype=bool)
        if variant == "exclusive":
            return _doubling([1.0] * n) <= 1.0
        groups: dict[str, list[int]] = {}
        for j, c in enumerate(self.relevant):
            groups.setdefault(self.net.groups[c], []).append(j)
        ok = np.ones(2 ** n, dtype=bool)
        for members in groups.values():
            ok &= _doubling([1.0 if j in members else 0.0 for j in range(n)]) <= 1.0
        return ok

    def state_posterior(self, variant: str, extra: Vec | None = None) -> Vec:
        """P(state | evidence) in one structure variant, optionally with one more
        likelihood factor over the states."""
        w = self._prior * self._likelihood * self.allowed(variant)
        if extra is not None:
            w = w * extra
        z = w.sum()
        if z <= 0.0:
            raise ValueError("the evidence has probability 0 in this structure")
        result: Vec = w / z
        return result

    def marginals(self, state_posterior: Vec) -> dict[str, float]:
        out = {}
        for j, c in enumerate(self.relevant):
            out[c] = float(state_posterior.reshape(-1, 2, 2 ** j)[:, 1, :].sum())
        return out

    def evidence_probability(self, variant: str) -> float:
        w = self._prior * self._likelihood * self.allowed(variant)
        z = self._prior * self.allowed(variant)
        return float(w.sum() / z.sum())


def pgmpy_posterior(net: Network, priors: Mapping[str, float], evidence: Evidence,
                    variant: str = "independent") -> dict[str, float]:
    """The same posterior by pgmpy variable elimination, for the conditions the evidence
    touches. A structure constraint becomes a binary child of the conditions that is
    observed true."""
    from pgmpy.factors.discrete import TabularCPD
    from pgmpy.inference import VariableElimination
    from pgmpy.models import DiscreteBayesianNetwork

    enum = Enumerator(net, priors, evidence)
    rel = list(enum.relevant)
    nodes = [(nid, net.node(nid)) for nid in evidence.values]
    model = DiscreteBayesianNetwork()
    model.add_nodes_from(rel)
    cpds = []
    for c in rel:
        p = min(max(priors[c], 0.0), 1.0)
        cpds.append(TabularCPD(c, 2, [[1.0 - p], [p]]))
    for nid, node in nodes:
        assert node is not None
        parents = [c for c in rel if c in node.links]
        for c in parents:
            model.add_edge(c, nid)
        cols = np.array(list(itertools.product((0, 1), repeat=len(parents))), dtype=float)
        logs = np.array([math.log1p(-min(node.links[c], 1.0 - EPS)) for c in parents])
        p1 = 1.0 - (1.0 - node.leak) * np.exp(cols @ logs)
        cpds.append(TabularCPD(nid, 2, np.vstack([1.0 - p1, p1]), evidence=parents,
                               evidence_card=[2] * len(parents)))
    evidence_states = {nid: int(v) for nid, v in evidence.values.items()}
    if variant != "independent":
        if len(rel) > MAX_PGMPY_CONSTRAINT:
            raise ValueError("too many conditions for the pgmpy constraint node")
        ok = enum.allowed(variant)
        # enumerator state index: bit j is rel[j]; pgmpy columns list the first parent slowest
        cols = np.array(list(itertools.product((0, 1), repeat=len(rel))), dtype=int)
        index = (cols * (1 << np.arange(len(rel)))).sum(axis=1)
        ok1 = ok[index].astype(float)
        for c in rel:
            model.add_edge(c, "__structure__")
        cpds.append(TabularCPD("__structure__", 2, np.vstack([1.0 - ok1, ok1]),
                               evidence=rel, evidence_card=[2] * len(rel)))
        evidence_states["__structure__"] = 1
    model.add_cpds(*cpds)
    model.check_model()
    ve = VariableElimination(model)
    out = {}
    for c in rel:
        q = ve.query([c], evidence=evidence_states, show_progress=False)
        out[c] = float(q.values[1])
    return out


@lru_cache(maxsize=1)
def bma_weights() -> Mapping[str, float]:
    """Variant weights from `bma_weights.json` (fitted on the validation split), else equal."""
    if WEIGHTS_FILE.exists():
        data = json.loads(WEIGHTS_FILE.read_text(encoding="utf-8"))
        return {v: float(data["weights"][v]) for v in VARIANTS}
    return {v: 1.0 / len(VARIANTS) for v in VARIANTS}


@dataclass(frozen=True)
class Item:
    node_id: str
    value: bool
    log_lr: float


@dataclass(frozen=True)
class Candidate:
    condition: str
    name: str
    probability: float
    prior: float
    prior_source: str
    for_: tuple[Item, ...] = ()
    against: tuple[Item, ...] = ()
    variants: Mapping[str, float] = field(default_factory=dict)


@dataclass(frozen=True)
class Differential:
    candidates: tuple[Candidate, ...]
    weights: Mapping[str, float]
    evidence: Mapping[str, bool]
    marginals: Mapping[str, float]
    unscored: tuple[str, ...] = ()
    dropped: tuple[str, ...] = ()

    def top(self) -> Candidate | None:
        return self.candidates[0] if self.candidates else None


def _log_lr(net: Network, nid: str, value: bool, condition: str) -> float:
    node = net.node(nid)
    assert node is not None
    p_with = 1.0 - (1.0 - node.leak) * (1.0 - node.links[condition])
    p_without = node.leak
    a, b = (p_with, p_without) if value else (1.0 - p_with, 1.0 - p_without)
    return math.log(max(a, EPS) / max(b, EPS))


class DifferentialModel:
    """`apdt.diagnosis.bn`: the BMA noisy-OR scorer."""

    def __init__(self, net: Network | None = None,
                 weights: Mapping[str, float] | None = None) -> None:
        self.net = net or build_network()
        self.weights = dict(weights or bma_weights())

    def priors(self, p: Patient) -> dict[str, tuple[float, str]]:
        return {c: prior_for(c, p) for c in self.net.conditions}

    def enumerator(self, p: Patient, obs: Observations) -> Enumerator:
        pri = self.priors(p)
        return Enumerator(self.net, {c: v[0] for c, v in pri.items()}, Evidence.of(obs, self.net))

    def mixture(self, enum: Enumerator, extra: Vec | None = None) -> Vec:
        """The weighted mixture of the variants' state posteriors."""
        total: Vec = np.zeros(2 ** len(enum.relevant))
        for v in VARIANTS:
            total = total + self.weights[v] * enum.state_posterior(v, extra)
        return total

    def differential(self, p: Patient, obs: Observations, *, engine: str = "enumerate"
                     ) -> Differential:
        pri = self.priors(p)
        evidence = Evidence.of(obs, self.net)
        enum = Enumerator(self.net, {c: v[0] for c, v in pri.items()}, evidence)
        per_variant: dict[str, dict[str, float]] = {}
        for v in VARIANTS:
            if engine == "pgmpy":
                per_variant[v] = pgmpy_posterior(self.net, enum.priors, evidence, v)
            else:
                per_variant[v] = enum.marginals(enum.state_posterior(v))
        marginals = {c: sum(self.weights[v] * per_variant[v][c] for v in VARIANTS)
                     for c in enum.relevant}
        candidates = []
        for c in enum.relevant:
            present = [(n, val) for n, val in evidence.values.items()
                       if c in (self.net.node(n).links if self.net.node(n) else {})]  # type: ignore[union-attr]
            pos = tuple(Item(n, val, _log_lr(self.net, n, val, c)) for n, val in present
                        if _log_lr(self.net, n, val, c) > 0)
            neg = tuple(Item(n, val, _log_lr(self.net, n, val, c)) for n, val in present
                        if _log_lr(self.net, n, val, c) < 0)
            if not pos or marginals[c] <= 0.0:
                continue
            candidates.append(Candidate(
                c, str(kb().entry(c).content()["name"]), marginals[c], pri[c][0], pri[c][1],
                pos, neg, {v: per_variant[v][c] for v in VARIANTS}))
        candidates.sort(key=lambda x: -x.probability)
        unscored = tuple(sorted(
            t for t in kb().ids() if t.startswith("test.") and t not in self.net.tests))
        return Differential(tuple(candidates), dict(self.weights), dict(evidence.values),
                            marginals, unscored, enum.dropped)


def write_weights(weights: Mapping[str, float], info: Mapping[str, Any],
                  path: Path = WEIGHTS_FILE) -> None:
    path.write_text(json.dumps({"weights": dict(weights), **info}, indent=1, sort_keys=True)
                    + "\n", encoding="utf-8")
    bma_weights.cache_clear()
