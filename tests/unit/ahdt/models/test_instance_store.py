from datetime import UTC, datetime, timedelta

import pytest

from ahdt.models.endocrine.glucose_insulin import GlucoseInsulinModel
from ahdt.models.organs import (
    ASSIMILATION,
    ForkExpired,
    InstanceStore,
    RevisionConflict,
)
from atra.connectors import DTKind
from tests.unit.ahdt.models.helpers import HDT

PANCREAS = "UBERON:0001264"


class Clock:
    def __init__(self) -> None:
        self.t = datetime(2026, 10, 1, 8, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
async def store(clock: Clock) -> InstanceStore:
    s = InstanceStore(now=clock)
    m = GlucoseInsulinModel()
    record = m.new_record(HDT, PANCREAS, DTKind.ENDOCRINE)
    await s.create(record.model_copy(update={"state": {**record.state,
                                                       "enzyme_secretion": 1.0}}))
    return s


async def test_create_checks_the_owner():
    s = InstanceStore()
    record = GlucoseInsulinModel().new_record(HDT, PANCREAS, DTKind.DIGESTIVE)
    with pytest.raises(PermissionError):
        await s.create(record)


async def test_facet_read_is_limited_to_consumers(store: InstanceStore):
    view = await store.get_facet(HDT, PANCREAS, "exocrine", consumer=DTKind.DIGESTIVE)
    assert view.fields == {"enzyme_secretion": 1.0}
    with pytest.raises(PermissionError):
        await store.get_facet(HDT, PANCREAS, "exocrine", consumer=DTKind.CARDIOVASCULAR)


async def test_only_owner_or_assimilation_writes(store: InstanceStore):
    with pytest.raises(PermissionError):
        await store.write(HDT, PANCREAS, writer=DTKind.DIGESTIVE, state={"G_p": 1.0},
                          params=None, expected_revision=0)
    r1 = await store.write(HDT, PANCREAS, writer=DTKind.ENDOCRINE, state={"G_p": 170.0},
                           params=None, expected_revision=0)
    r2 = await store.write(HDT, PANCREAS, writer=ASSIMILATION, state={"G_p": 171.0},
                           params={"V_mX": 0.03}, expected_revision=1,
                           uncertainty={"V_mX": {"std": 0.005}})
    assert (r1.revision, r2.revision) == (1, 2)
    assert r2.last_assimilated is not None
    assert r2.params == {"V_mX": 0.03}
    assert r2.state["G_t"] == r1.state["G_t"]


async def test_stale_revision_fails(store: InstanceStore):
    await store.write(HDT, PANCREAS, writer=DTKind.ENDOCRINE, state={"G_p": 170.0},
                      params=None, expected_revision=0)
    with pytest.raises(RevisionConflict):
        await store.write(HDT, PANCREAS, writer=DTKind.ENDOCRINE, state={"G_p": 160.0},
                          params=None, expected_revision=0)


async def test_as_of_reads_history(store: InstanceStore, clock: Clock):
    before = clock.t
    clock.t += timedelta(minutes=5)
    await store.write(HDT, PANCREAS, writer=DTKind.ENDOCRINE, state={"enzyme_secretion": 0.4},
                      params=None, expected_revision=0)
    old = await store.get_facet(HDT, PANCREAS, "exocrine", consumer=DTKind.DIGESTIVE,
                                as_of=before)
    new = await store.get_facet(HDT, PANCREAS, "exocrine", consumer=DTKind.DIGESTIVE)
    assert (old.fields["enzyme_secretion"], new.fields["enzyme_secretion"]) == (1.0, 0.4)


async def test_fork_isolates_writes_and_expires(store: InstanceStore, clock: Clock):
    fork = await store.fork(HDT, [PANCREAS])
    await fork.write(HDT, PANCREAS, writer=DTKind.ENDOCRINE, state={"enzyme_secretion": 0.1},
                     params=None, expected_revision=0)
    forked = await fork.get_facet(HDT, PANCREAS, "exocrine", consumer=DTKind.DIGESTIVE)
    main = await store.get_facet(HDT, PANCREAS, "exocrine", consumer=DTKind.DIGESTIVE)
    assert forked.fields["enzyme_secretion"] == 0.1 and forked.fork_id == fork.fork_id
    assert main.fields["enzyme_secretion"] == 1.0 and main.revision == 0
    clock.t += timedelta(minutes=16)
    with pytest.raises(ForkExpired):
        await fork.get(HDT, PANCREAS)
    assert fork.fork_id not in store.forks()


async def test_release_ends_a_fork(store: InstanceStore):
    fork = await store.fork(HDT, [PANCREAS])
    await store.release(fork.fork_id)
    with pytest.raises(ForkExpired):
        await fork.get(HDT, PANCREAS)
