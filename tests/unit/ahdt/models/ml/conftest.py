from pathlib import Path

import pytest

from ahdt.models.ml.artifacts import Result
from evaluation.models.ahdt import train as tasks
from synth import training as synthetic

# Few persons have a respiratory condition or a fall-risk gait record, so these two models
# need a larger population for a non-empty test split.
LARGER = ("ahdt.respiratory.exacerbation_risk", "ahdt.musculoskeletal.gait_and_fall_risk")


@pytest.fixture(scope="session")
def pop() -> tasks.Population:
    return synthetic.population(200)


@pytest.fixture(scope="session")
def trained(pop: tasks.Population, tmp_path_factory: pytest.TempPathFactory
            ) -> tuple[Path, dict[str, Result]]:
    """Every laptop model trained once, quickly, into a temporary root."""
    root = tmp_path_factory.mktemp("t1")
    big = synthetic.population(400)
    results = {m: fn(big if m in LARGER else pop, root / m, m, True)
               for m, fn in tasks.TRAINERS.items()}
    return root, results
