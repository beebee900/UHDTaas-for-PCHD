from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml

from ahdt.models.reference import ReferenceStateDef, ReferenceStateModel
from atra import contracts as c
from atra.connectors import DTKind
from atra.kb import KnowledgeBase
from tests.unit.ahdt.models.helpers import observation

DRAFT = {"status": "draft", "assumption": True, "justification": "test value"}
DEFINITION = ReferenceStateDef.model_validate({
    "model_id": "ahdt.haematological.coagulation", "twin": "haematological",
    "intended_use": "test", "instances": ["UBERON:0000178"],
    "variables": {
        "inr": {"unit": "{INR}", "ref": "range.inr", "tau_h": 24, "justification": "test"},
        "weeks": {"unit": "wk", "ref": "state.weeks", "tau_h": 24, "justification": "test",
                  "hold": True},
        "unsourced": {"unit": "1", "ref": "state.unsourced", "tau_h": 24,
                      "justification": "test"}},
    "couplings": [{"input": "synthesis", "from": "facet:UBERON:0002107/haematological",
                   "unit": "1", "target": "inr", "gain": "g.inr", "reference": "r.inr"}],
    "obs_map": {"6301-6": "inr"}})


@pytest.fixture
def kb(tmp_path: Path) -> KnowledgeBase:
    entries = [
        {"id": "range.inr", "normal": 1.0, "ref_low": 0.8, "ref_high": 1.2, "warn_low": None,
         "warn_high": 3.0, "crit_low": None, "crit_high": 5.0, "provenance": DRAFT},
        {"id": "state.weeks", "normal": 20, "provenance": DRAFT},
        {"id": "state.unsourced", "normal": None, "provenance": DRAFT},
        {"id": "g.inr", "value": -2.0, "provenance": DRAFT},
        {"id": "r.inr", "value": 1.0, "provenance": DRAFT},
    ]
    (tmp_path / "test.yaml").write_text(yaml.safe_dump(entries))
    return KnowledgeBase(tmp_path)


def record(model: ReferenceStateModel, **state: float) -> c.InstanceRecord:
    p = model.parameters()
    return c.InstanceRecord(instance_id="inst-hdt-0123456789ab-0000178",
                            anatomy="UBERON:0000178", model_id=model.model_id,
                            version=model.version, owner_dt=DTKind.HAEMATOLOGICAL, params={},
                            state={**model.initial_state(p, {}), **state})


def test_status_bands(kb):
    m = ReferenceStateModel(DEFINITION, kb)
    assert m.status("inr", 1.0) == "normal"
    assert m.status("inr", 1.5) == "abnormal"
    assert m.status("inr", 4.0) == "warning"
    assert m.status("inr", 6.0) == "critical"
    assert m.status("unsourced", 0.3) == "unknown"


async def test_relaxes_to_a_coupled_target(kb):
    m = ReferenceStateModel(DEFINITION, kb)
    tr = await m.simulate(record(m), c.Scenario(kind="intervention"), 30 * 86400, 86400,
                          inputs={"synthesis": 0.5})
    assert tr.series["inr"][-1] == pytest.approx(1.0 + -2.0 * (0.5 - 1.0), abs=1e-3)


async def test_held_and_unsourced_variables(kb):
    m = ReferenceStateModel(DEFINITION, kb)
    tr = await m.simulate(record(m, weeks=31.0, unsourced=0.4), c.Scenario(kind="intervention"),
                          10 * 86400, 86400)
    assert tr.series["weeks"][-1] == pytest.approx(31.0)
    assert tr.series["unsourced"][-1] == pytest.approx(0.4)


async def test_observation_sets_state_and_status(kb):
    m = ReferenceStateModel(DEFINITION, kb)
    obs = [observation("6301-6", 3.4, "{INR}", datetime(2026, 10, 1, tzinfo=UTC),
                       DTKind.HAEMATOLOGICAL)]
    fitted = await m.calibrate(record(m), obs)
    assert fitted.state["inr"] == 3.4 and fitted.state["inr_status"] == "warning"


def test_unknown_without_a_sourced_normal(kb):
    m = ReferenceStateModel(DEFINITION, kb)
    state = m.initial_state(m.parameters(), {})
    assert state["unsourced"] is None
    out = m.evaluate(m.parameters(), state, {})
    assert "unsourced" not in out and out["unsourced_status"] == "unknown"
