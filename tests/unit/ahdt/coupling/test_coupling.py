import asyncio
import json
from types import SimpleNamespace

import pytest

from ahdt.coupling.connectors import range_band, system_connector
from ahdt.coupling.inbox import Delivery, ReorderBuffer
from ahdt.coupling.manager import connector_name, hdt_pairs
from ahdt.coupling.state import TwinStateProvider
from ahdt.models.base import Port
from ahdt.models.coupling import resolve_inputs
from ahdt.models.organs.store import InstanceStore
from ahdt.registry import load_registry
from atra.connection import ConnectorEnvelope
from atra.connectors import DTKind as K
from atra.connectors import Message, PolicyDenied
from atra.contracts import InstanceRecord
from atra.ids import instance_id

from .cases import CASES, st
from .conftest import HDT


async def test_coupling_matrix_lists_every_connector_of_the_hdt(rig):
    view = rig.coupling.view()
    registry = load_registry()
    names = {r["name"] for r in view["connectors"]}
    assert view["running"] and view["count"] == len(names) == 53
    assert names == {connector_name(*p) for p in hdt_pairs(registry)}
    for kind, twin in registry.twins.items():
        for name in twin.connectors_out:
            assert any(r["connector"] == name and r["source"] == kind.value
                       for r in view["connectors"]), (kind, name)
        for name in twin.connectors_in:
            assert any(r["connector"] == name and r["target"] == kind.value
                       for r in view["connectors"]), (kind, name)
    summaries = [r for r in view["connectors"] if r["connector"] == "SystemToWholeBodyConnector"]
    assert {r["source"] for r in summaries} == {k.value for k in K if k.is_physiological}
    assert view["matrix"]["cardiovascular"]["respiratory"] == ["haemodynamics"]
    assert view["matrix"]["respiratory"]["cardiovascular"] == ["gas_exchange"]
    row = next(r for r in view["connectors"] if r["connector"] == "PriorConnector")
    assert row["purposes"] == ["care", "public_health"] and row["mode"] == "request_reply"
    assert row["topics"]["dlq"].endswith("/population_prior/v1.dlq")


def test_generated_summary_connectors_are_distinct_classes():
    cv, resp = system_connector(K.CARDIOVASCULAR), system_connector(K.RESPIRATORY)
    assert cv is not resp and cv.SOURCE_KIND is K.CARDIOVASCULAR
    assert cv.spec_name() == "SystemToWholeBodyConnector"
    assert [f.name for f in cv.FIELDS][:2] == ["heart_rate", "sbp"]
    with pytest.raises(ValueError):
        system_connector(K.SOCIAL)


@pytest.mark.parametrize(("value", "band", "status"), [
    (37.0, "normal", "normal"), (38.5, "abnormal", "watch"), (39.5, "warning", "watch"),
    (34.0, "critical", "alert")])
async def test_summary_status_uses_kb_reference_bands(rig, value, band, status):
    assert range_band("range.temperature", value) == band
    c = rig.coupling.get("SystemToWholeBodyConnector", K.IMMUNE_LYMPHATIC, K.WHOLE_BODY)
    msg = await c.publish(st({}, fields={"temperature": {"value": value, "unit": "Cel"}}))
    assert msg.payload == {"key_values": {"temperature": value}, "status": status}


async def test_units_are_converted_to_the_contract(rig):
    c = rig.coupling.get("InfectionNeuroConnector", K.IMMUNE_LYMPHATIC, K.NERVOUS)
    msg = await c.publish(st({"inflammation_index": 0.2}, {"inflammation_index": "1"},
                             {"temperature": {"value": 102.2, "unit": "[degF]"}},
                             {"conditions": []}))
    assert msg.payload["core_temp"] == pytest.approx(39.0)


async def test_range_guard_refuses_and_dead_letters(rig):
    c = rig.coupling.get("InfectionHaemodynamicsConnector", K.IMMUNE_LYMPHATIC,
                         K.CARDIOVASCULAR)
    state = st({"inflammation_index": 0.3}, {"inflammation_index": "1"},
               {"temperature": {"value": 43.5, "unit": "Cel"}}, {"conditions": []})
    with pytest.raises(PolicyDenied, match="range_guard"):
        await c.publish(state)
    assert c.dead_letters[0]["reason"].startswith("range_guard")


async def test_publish_from_reports_each_connector(rig):
    results = await rig.coupling.publish_from(K.IMMUNE_LYMPHATIC,
                                              CASES["InfectionNeuroConnector"].valid)
    by_name = {r.connector.split(":")[0]: r for r in results}
    assert set(by_name) == {"HaemolysisConnector", "InfectionHaemodynamicsConnector",
                            "InfectionNeuroConnector", "SystemToWholeBodyConnector"}
    assert by_name["InfectionNeuroConnector"].message is not None
    assert "parasitaemia: missing" in by_name["HaemolysisConnector"].error


async def test_messages_match_the_published_envelope_schema(rig):
    c = rig.coupling.get("GlucoseRenalConnector", K.ENDOCRINE, K.RENAL_URINARY)
    msg = await c.publish(CASES["GlucoseRenalConnector"].valid)
    ConnectorEnvelope.model_validate(json.loads(msg.to_bytes()))


def _delivery(sim_time, hlc, label):
    msg = Message(source="a", target="b", contract="x/v1.0", payload={"label": label},
                  units={}, sim_time=sim_time, provenance={"hlc": hlc})
    return Delivery("X", "X:a->b", K.RENAL_URINARY, K.WHOLE_BODY, "t", msg)


async def test_reorder_buffer_orders_by_sim_time_then_hlc_within_the_window():
    now = [100.0]
    out = []

    async def release(d):
        out.append(d.message.payload["label"])

    buf = ReorderBuffer(release, window_s=2.0, clock=lambda: now[0])
    await buf.add(_delivery(20.0, "1000.0.n1", "late"))
    await buf.add(_delivery(10.0, "1002.0.n2", "b"))
    await buf.add(_delivery(10.0, "1001.5.n1", "a"))
    assert await buf.release_due() == 0 and out == []
    now[0] = 102.0
    assert await buf.release_due() == 3
    assert out == ["a", "b", "late"]


async def test_reorder_buffer_releases_after_the_window_by_itself():
    out = []

    async def release(d):
        out.append(d.message.payload["label"])

    buf = ReorderBuffer(release, window_s=0.05)
    await buf.add(_delivery(5.0, "1.0.n", "second"))
    await buf.add(_delivery(1.0, "2.0.n", "first"))
    await asyncio.sleep(0.2)
    assert out == ["first", "second"] and len(buf) == 0


async def test_state_provider_feeds_connectors_and_model_ports(rig):
    store = InstanceStore()
    anatomy = load_registry().get(K.NERVOUS).owns_instances[0]
    await store.create(InstanceRecord(
        instance_id=instance_id(HDT, anatomy), anatomy=anatomy, model_id="m.nervous",
        version="1.0.0", owner_dt=K.NERVOUS, params={},
        state={"stress_drive": 0.35, "circadian_phase": 7.0}))
    provider = TwinStateProvider(store, units={K.NERVOUS: {"stress_drive": "1",
                                                           "circadian_phase": "h"}})
    state = await provider.state(HDT, K.NERVOUS)
    assert state["_models"] == {anatomy: "m.nervous@1.0.0"}
    c = rig.coupling.get("NeuroEndocrineConnector", K.NERVOUS, K.ENDOCRINE)
    await c.publish(state)
    model = SimpleNamespace(spec=SimpleNamespace(twin=K.ENDOCRINE, inputs=(
        Port("stress_drive", "1", "connector:NeuroEndocrineConnector#stress_drive"),
        Port("clock_h", "h", "connector:NeuroEndocrineConnector#circadian_phase"))))
    values = await resolve_inputs(model, HDT,
                                  connectors=rig.coupling.inbox.payloads(K.ENDOCRINE))
    assert values == {"stress_drive": 0.35, "clock_h": 7.0}
