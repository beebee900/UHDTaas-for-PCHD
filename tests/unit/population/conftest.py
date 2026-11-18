import numpy as np
import pandas as pd
import pytest

from ahdt.models.ml import population as wp14b
from ahdt.models.ml.common import age_band
from ahdt.models.ml.slices import bands
from atra.config import get_settings
from atra.kb import KnowledgeBase
from population.priors import MODEL_ID, PopulationPriors

REGIONS = ("island_and_coast", "mainland_core", "north_west", "west_and_ikorodu")
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")


def person_frames(n: int, seed: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Random persons, under-five malaria months and field values in the WP14b layout."""
    rng = np.random.default_rng(seed)
    age = rng.integers(0, 85, n)
    persons = pd.DataFrame({
        "hdt_id": [f"hdt-{seed:04x}{i:08x}" for i in range(n)], "age_years": age,
        "sex": rng.choice(["female", "male"], n), "age_band": [age_band(a, bands()) for a in age],
        "region": rng.choice(REGIONS, n), "facility_level": rng.choice(["primary", "secondary"], n),
        "language": rng.choice(["en", "yo"], n)})
    for cond, p in zip(wp14b.CONDITIONS, (0.25, 0.08, 0.03), strict=True):
        persons[cond] = (rng.random(n) < p * (age >= 15)).astype(int)
    under5 = persons[persons.age_years < 5]
    rate = {m: 0.08 if m in wp14b.RAINY else 0.03 for m in MONTHS}
    episodes = pd.DataFrame([{"hdt_id": h, "month": m, wp14b.MALARIA: int(rng.random() < rate[m])}
                             for h in under5.hdt_id for m in MONTHS])
    fields = persons[["hdt_id", *wp14b.ATTRIBUTES]].assign(
        sbp=rng.normal(125, 15, n), glucose=rng.normal(5.2, 0.8, n))
    return persons, episodes, fields


@pytest.fixture(scope="session")
def priors_root(tmp_path_factory):
    root = tmp_path_factory.mktemp("models")
    persons, episodes, fields = person_frames(1500, 3)
    wp14b.train_priors(MODEL_ID, "1.0.0", persons, episodes, fields, root / MODEL_ID)
    return root


@pytest.fixture(scope="session")
def kb():
    return KnowledgeBase(get_settings().kb_dir)


@pytest.fixture
def priors(priors_root, kb):
    return PopulationPriors.load(kb, priors_root)
