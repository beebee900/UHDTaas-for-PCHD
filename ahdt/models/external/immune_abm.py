"""Within-host adaptive immune response as a Mesa agent-based model (design 04, 4.5.3).

Cells live on a periodic grid that stands for a lymph node section. One tick is 30 minutes
and one grid cell is 100 micrometres.

- Dendritic cells appear in proportion to the antigen load and present antigen for a fixed life.
- A naive T cell that shares a grid cell with a dendritic cell becomes an effector T cell.
- Effector T cells divide until the effector population reaches its limit. When the antigen is
  cleared they die; a fraction becomes memory cells.
- A naive B cell that shares a grid cell with an effector T cell becomes a plasma cell, which
  secretes antibody. Antibody neutralises antigen and decays with its half-life.
- Macrophages take up antigen on contact; effector T cells in the same grid cell activate them.
- Effector T cells kill antigen at a rate that saturates with their number.
- A memory cell that meets antigen again becomes an effector cell.
- Antigen replicates until it reaches its ceiling.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

import mesa
from mesa.discrete_space import CellAgent, OrthogonalMooreGrid

TICK_MIN = 30.0
TICKS_PER_DAY = 1440.0 / TICK_MIN


@dataclass
class Counts:
    naive_t: int = 0
    effector_t: int = 0
    memory_t: int = 0
    naive_b: int = 0
    plasma: int = 0
    macrophage_active: int = 0
    dendritic: int = 0
    antibody: float = 0.0
    antigen: float = 0.0
    history: list[dict[str, float]] = field(default_factory=list)


class _Cell(CellAgent):
    def wander(self) -> None:
        self.cell = self.cell.neighborhood.select_random_cell()  # type: ignore[has-type]

    def mates(self, kind: type) -> list[Any]:
        return [a for a in self.cell.agents if isinstance(a, kind)]


class TCell(_Cell):
    def __init__(self, model: ImmuneModel, cell: Any, state: str = "naive") -> None:
        super().__init__(model)
        self.cell = cell
        self.state = ""
        self.age = 0
        self.become(state)

    def become(self, state: str) -> None:
        m: ImmuneModel = self.model
        m.n_effector += (state == "effector") - (self.state == "effector")
        self.state, self.age = state, 0

    def die(self) -> None:
        self.become("gone")
        self.remove()

    def step(self) -> None:
        m: ImmuneModel = self.model
        p = m.p
        self.wander()
        if self.state == "naive":
            if self.mates(DendriticCell) and m.random.random() < p["p_activation"]:
                self.become("effector")
        elif self.state == "effector":
            self.age += 1
            if m.antigen < p["antigen_clearance_threshold"]:
                if m.random.random() < p["effector_death_rate"]:
                    if m.random.random() < p["memory_fraction"]:
                        self.become("memory")
                    else:
                        self.die()
                return
            if self.age % int(p["division_ticks"]) == 0 and m.n_effector < p["effector_limit"]:
                TCell(m, self.cell, "effector")
        elif m.antigen >= p["antigen_clearance_threshold"] \
                and m.random.random() < p["p_memory_recall"]:
            self.become("effector")


class BCell(_Cell):
    def __init__(self, model: ImmuneModel, cell: Any, state: str = "naive") -> None:
        super().__init__(model)
        self.cell = cell
        self.state = state

    def step(self) -> None:
        m: ImmuneModel = self.model
        p = m.p
        if self.state == "naive":
            self.wander()
            helpers = [t for t in self.mates(TCell) if t.state == "effector"]
            if helpers and m.antigen > 0 and m.random.random() < p["p_b_activation"]:
                self.state = "plasma"
        else:
            m.antibody += p["antibody_secretion"]
            if m.random.random() < p["plasma_death_rate"]:
                self.remove()


class Macrophage(_Cell):
    def __init__(self, model: ImmuneModel, cell: Any) -> None:
        super().__init__(model)
        self.cell = cell
        self.active = False

    def step(self) -> None:
        m: ImmuneModel = self.model
        p = m.p
        self.wander()
        if not self.active and any(t.state == "effector" for t in self.mates(TCell)):
            self.active = True
        if m.antigen > 0:
            rate = p["uptake_active"] if self.active else p["uptake_resting"]
            m.antigen = max(0.0, m.antigen - rate * m.antigen / (m.antigen + p["uptake_half"]))


class DendriticCell(_Cell):
    def __init__(self, model: ImmuneModel, cell: Any) -> None:
        super().__init__(model)
        self.cell = cell
        self.age = 0

    def step(self) -> None:
        self.age += 1
        if self.age >= self.model.p["dendritic_lifetime_ticks"]:
            self.remove()


class ImmuneModel(mesa.Model):
    def __init__(self, p: Mapping[str, float], seed: int, antigen: float,
                 initial: Mapping[str, float] | None = None) -> None:
        super().__init__(rng=seed)
        self.p = dict(p)
        self.n_effector = 0
        size = int(p["grid_size"])
        self.grid = OrthogonalMooreGrid((size, size), torus=True, random=self.random)
        cells = self.grid.all_cells.cells
        init = initial or {}
        for _ in range(int(init.get("naive_t", p["naive_t"]))):
            TCell(self, self.random.choice(cells))
        for _ in range(int(init.get("memory_t", 0))):
            TCell(self, self.random.choice(cells), "memory")
        for _ in range(int(init.get("naive_b", p["naive_b"]))):
            BCell(self, self.random.choice(cells))
        for _ in range(int(init.get("plasma", 0))):
            BCell(self, self.random.choice(cells), "plasma")
        for _ in range(int(p["macrophages"])):
            Macrophage(self, self.random.choice(cells))
        self.antigen = antigen
        self.antibody = float(init.get("antibody", 0.0))
        self.tick = 0

    def step(self) -> None:
        p = self.p
        if self.antigen > 0:
            self.antigen = min(p["antigen_ceiling"], self.antigen * (1 + p["antigen_growth"]))
            arrivals = p["dendritic_arrival"] * self.antigen / (self.antigen + p["antigen_half"])
            while arrivals > 0:
                if self.random.random() < min(arrivals, 1.0):
                    DendriticCell(self, self.random.choice(self.grid.all_cells.cells))
                arrivals -= 1.0
            killed = p["effector_kill"] * self.n_effector / (self.n_effector
                                                            + p["effector_kill_half"])
            bound = min(0.5, p["neutralisation"] * self.antibody)
            self.antigen *= (1.0 - killed) * (1.0 - bound)
            if self.antigen < p["antigen_floor"]:
                self.antigen = 0.0
        self.antibody *= math.exp(-math.log(2) / p["antibody_half_life_ticks"])
        self.agents.shuffle_do("step")
        self.tick += 1

    def counts(self) -> Counts:
        c = Counts(antibody=self.antibody, antigen=self.antigen)
        for a in self.agents:
            if isinstance(a, TCell):
                if a.state == "naive":
                    c.naive_t += 1
                elif a.state == "effector":
                    c.effector_t += 1
                else:
                    c.memory_t += 1
            elif isinstance(a, BCell):
                if a.state == "naive":
                    c.naive_b += 1
                else:
                    c.plasma += 1
            elif isinstance(a, Macrophage) and a.active:
                c.macrophage_active += 1
            elif isinstance(a, DendriticCell):
                c.dendritic += 1
        return c


def run(p: Mapping[str, float], seed: int, antigen: float, days: float,
        sample_every_ticks: int, initial: Mapping[str, float] | None = None) -> list[Counts]:
    model = ImmuneModel(p, seed, antigen, initial)
    out = [model.counts()]
    for tick in range(1, int(days * TICKS_PER_DAY) + 1):
        model.step()
        if tick % sample_every_ticks == 0:
            out.append(model.counts())
    return out
