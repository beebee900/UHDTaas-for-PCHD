from ahdt.models.organs.store import InstanceStore
from population.trial import HEART, InSilicoTrial


async def test_a_100_subject_in_silico_trial(kb):
    """Acceptance: 100 virtual twins, one fork each, and an outcome summary."""
    store = InstanceStore()
    result = await InSilicoTrial(store, kb=kb).run(subjects=100, seed=1)
    s = result.summary()
    assert s["subjects"] == 100 and s["forks_released"] == 100
    assert s["mean_difference"] < 0
    assert s["mean_difference_95ci"][0] < s["mean_difference"] < s["mean_difference_95ci"][1] < 0
    assert s["controlled_share_treated"] >= s["controlled_share_control"]
    assert s["threshold_sbp"] == 140
    assert store.forks() == {}
    twin = result.outcomes[0]
    record = await store.get(twin.hdt_id, HEART)
    assert record.state["sbp"] == twin.control_sbp and record.params
