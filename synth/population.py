"""Persons, households, the social network, SDoH and genotypes (design 06, 6.4.1).

Everything is drawn from one seeded generator in a fixed order, so the same seed gives the
same population. `hdt_id`s come from synthetic national ids with the demo HMAC key, as for
the personas, so every service derives the same ids.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any

import networkx as nx
import numpy as np

from atra.ids import hdt_id_for
from atra.personas import DEMO_HDT_KEY
from synth.params import allele_frequencies, prior, sources


@dataclass
class Person:
    hdt_id: str
    national_id: str
    sex: str
    age_years: int
    lga: str
    household_id: str
    sdoh: dict[str, Any]
    hb_genotype: str
    pgx: dict[str, str]
    conditions: list[str] = field(default_factory=list)

    def record(self) -> dict[str, Any]:
        return asdict(self)


def _choice(rng: np.random.Generator, shares: Mapping[Any, float]) -> Any:
    keys = list(shares)
    p = np.asarray([shares[k] for k in keys], dtype=float)
    return keys[int(rng.choice(len(keys), p=p / p.sum()))]


def _age(rng: np.random.Generator, band: str) -> int:
    lo, hi = (int(x) for x in band.split("-"))
    return int(rng.integers(lo, hi))


def _hb_genotype(rng: np.random.Generator) -> str:
    scd = prior("sickle_cell")
    p_ss = float(scd["community_based_pct"]) / 100.0
    p_as = float(scd["trait_pct"]) / 100.0
    u = rng.random()
    return "HbSS" if u < p_ss else "HbAS" if u < p_ss + p_as else "HbAA"


def _pgx(rng: np.random.Generator, sex: str) -> dict[str, str]:
    out = {}
    for gene, alleles in sorted(allele_frequencies().items()):
        names = [a for a, _ in alleles]
        p = np.asarray([f for _, f in alleles])
        if gene == "G6PD" and sex == "male":
            out[gene] = names[int(rng.choice(len(names), p=p))]
        else:
            a, b = sorted(names[int(i)] for i in rng.choice(len(names), size=2, p=p))
            out[gene] = f"{a}/{b}"
    return out


def generate(n: int, seed: int) -> tuple[list[Person], nx.Graph]:
    src = sources()
    rng = np.random.default_rng(seed)
    lgas: Sequence[str] = src["lgas"]["values"]
    sizes = {int(k): v for k, v in src["household_size"]["values"].items()}
    sdoh = src["sdoh"]
    persons: list[Person] = []
    household = 0
    while len(persons) < n:
        size = min(_choice(rng, sizes), n - len(persons))
        lga = lgas[int(rng.integers(len(lgas)))]
        hid = f"hh-{seed}-{household:06d}"
        household += 1
        for _ in range(size):
            i = len(persons)
            national = f"SYN-POP-{seed}-{i:07d}"
            sex = "female" if rng.random() < src["sex_female_share"]["value"] else "male"
            age = _age(rng, _choice(rng, src["age_bands"]["values"]))
            persons.append(Person(
                hdt_id=hdt_id_for(national, DEMO_HDT_KEY), national_id=national, sex=sex,
                age_years=age, lga=lga, household_id=hid,
                sdoh={"income_band": _choice(rng, sdoh["income_band"]["values"]),
                      "education": _choice(rng, sdoh["education"]["values"]),
                      "improved_water": bool(rng.random() < sdoh["improved_water"]["value"]),
                      "improved_sanitation": bool(
                          rng.random() < sdoh["improved_sanitation"]["value"]),
                      "nhia_insured": bool(rng.random() < sdoh["nhia_insured"]["value"])},
                hb_genotype=_hb_genotype(rng), pgx=_pgx(rng, sex)))
    return persons, network(persons, seed)


def network(persons: Sequence[Person], seed: int) -> nx.Graph:
    """Household cliques plus a Watts-Strogatz small world inside each LGA."""
    cfg = sources()["network"]
    g = nx.Graph()
    g.add_nodes_from(p.hdt_id for p in persons)
    by_household: dict[str, list[str]] = {}
    by_lga: dict[str, list[str]] = {}
    for p in persons:
        by_household.setdefault(p.household_id, []).append(p.hdt_id)
        by_lga.setdefault(p.lga, []).append(p.hdt_id)
    for members in by_household.values():
        g.add_edges_from((a, b, {"kind": "household"}) for i, a in enumerate(members)
                         for b in members[i + 1:])
    for j, lga in enumerate(sorted(by_lga)):
        members = by_lga[lga]
        if len(members) <= cfg["k"]:
            continue
        ws = nx.watts_strogatz_graph(len(members), cfg["k"], cfg["p"], seed=seed + j)
        for a, b in ws.edges():
            if not g.has_edge(members[a], members[b]):
                g.add_edge(members[a], members[b], kind="community")
    return g
