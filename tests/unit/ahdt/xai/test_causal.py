"""The hypoglycaemia graph of design 04, 4.6.2, rebuilt from provenance."""

from __future__ import annotations

import pytest

from ahdt.coupling.connectors import connector_class
from ahdt.models.endocrine.glucose_insulin import GlucoseInsulinModel
from ahdt.xai.causal import CausalGraphBuilder, ProvenanceRecorder, persist
from atra import contracts as c
from atra.backends.graph import NetworkXGraph
from atra.connectors import DTKind, InMemoryTransport, TwinEndpoint
from atra.ids import new_output_id
from atra.provenance import ProvenanceStore

HDT = "hdt-0123456789ab"
ENDO, BEHAV, WB = DTKind.ENDOCRINE, DTKind.BEHAVIOURAL_COGNITIVE, DTKind.WHOLE_BODY


async def _min_glucose(model: GlucoseInsulinModel, carbs_g: float) -> float:
    record = model.new_record(HDT, model.spec.instances[0], ENDO)
    scenario = c.Scenario(kind="diet", diet={"meals": [{"t_s": 0, "carbs_g": carbs_g}]})
    tr = await model.simulate(record, scenario, 4 * 3600, 600)
    return min(tr.series["glucose"])


async def run_scenario(store: ProvenanceStore) -> dict[str, str]:
    """Behavioural meal report -> connector -> Endocrine glucose run, with the Whole-Body
    insulin record and a CGM reading as further inputs; then the Endocrine summary goes to
    Whole-Body through its connector and the Whole-Body early-warning model runs."""
    rec = ProvenanceRecorder(store)
    transport = InMemoryTransport()
    meal = rec.observation("obs-meal", hdt_id=HDT, field_name="carb_intake",
                           twin="behavioural_cognitive")
    insulin = rec.observation("obs-insulin", hdt_id=HDT, field_name="insulin_dose",
                              twin="whole_body")
    cgm = rec.observation("obs-cgm", hdt_id=HDT, field_name="glucose", twin="endocrine")

    cls = connector_class("EndocrineBehaviouralConnector", ENDO)
    link = cls(TwinEndpoint(HDT, ENDO), TwinEndpoint(HDT, BEHAV), transport,
               provenance_store=store)
    await link.start()
    m1 = await link.reply_from({"fields": {"active_minutes": {"value": 20.0, "unit": "min"},
                                           "sleep_duration": {"value": 7.0, "unit": "h"},
                                           "carb_intake": {"value": 20.0, "unit": "g"}}})
    rec.link_message(m1.provenance["prov_id"], meal)

    model = GlucoseInsulinModel()
    carbs = float(m1.payload["carbohydrate_g"])
    low, usual = await _min_glucose(model, carbs), await _min_glucose(model, 80.0)
    out_endo = new_output_id()
    rec.model_run(out_endo, model.model_id, model.version, hdt_id=HDT,
                  used=[m1.provenance["prov_id"], insulin, cgm], twin="endocrine")
    rec.attributions(out_endo, {m1.provenance["prov_id"]: abs(usual - low)},
                     "sensitivity.local@own")

    sys_cls = connector_class("SystemToWholeBodyConnector", ENDO)
    up = sys_cls(TwinEndpoint(HDT, ENDO), TwinEndpoint(HDT, WB), transport,
                 provenance_store=store)
    await up.start()
    m2 = await up.publish({"state": {"glucose": low, "glucose_status": "critical"},
                            "units": {"glucose": "mmol/L"}})
    assert m2 is not None
    rec.link_message(m2.provenance["prov_id"], out_endo)

    out_wb = new_output_id()
    rec.model_run(out_wb, "ahdt.whole_body.early_warning", "1.0.0", hdt_id=HDT,
                  used=[m2.provenance["prov_id"]], twin="whole_body")
    return {"endo": out_endo, "wb": out_wb, "m1": m1.provenance["prov_id"],
            "m2": m2.provenance["prov_id"], "meal": meal, "insulin": insulin, "cgm": cgm}


@pytest.fixture
async def scenario():
    store = ProvenanceStore("ahdt")
    return store, await run_scenario(store)


async def test_endocrine_output_reaches_behavioural_and_whole_body(scenario):
    store, ids = scenario
    g = CausalGraphBuilder(store).build(ids["endo"])
    q = lambda e: e if e.startswith("atra:") else f"atra:{e}"  # noqa: E731
    assert {q(ids["endo"]), q(ids["m1"]), q(ids["meal"]), q(ids["insulin"]),
            q(ids["cgm"])} == set(g.nodes)
    assert g.twins() == {"endocrine", "behavioural_cognitive", "whole_body"}
    weights = {e.source: e.weight for e in g.edges if e.target == q(ids["endo"])}
    assert weights[q(ids["m1"])] > 0 and weights[q(ids["m1"])] != 1.0
    assert weights[q(ids["insulin"])] == 1.0 and weights[q(ids["cgm"])] == 1.0
    into_msg = [e for e in g.edges if e.target == q(ids["m1"])]
    assert [e.source for e in into_msg] == [q(ids["meal"])]


async def test_whole_body_output_follows_the_message_to_the_endocrine_run(scenario):
    store, ids = scenario
    g = CausalGraphBuilder(store).build(ids["wb"])
    q = lambda e: e if e.startswith("atra:") else f"atra:{e}"  # noqa: E731
    assert {q(ids["wb"]), q(ids["m2"]), q(ids["endo"]), q(ids["m1"]), q(ids["meal"]),
            q(ids["insulin"]), q(ids["cgm"])} == set(g.nodes)
    path = [(e.source, e.target) for e in g.edges]
    assert (q(ids["endo"]), q(ids["m2"])) in path and (q(ids["m2"]), q(ids["wb"])) in path


async def test_graph_is_rebuilt_from_serialised_provenance(scenario):
    store, ids = scenario
    direct = CausalGraphBuilder(store).build(ids["wb"])
    again = CausalGraphBuilder(store.serialize()).build(ids["wb"])
    assert set(again.nodes) == set(direct.nodes)
    assert {(e.source, e.target, e.weight) for e in again.edges} == \
        {(e.source, e.target, e.weight) for e in direct.edges}


async def test_a_different_history_gives_a_different_graph():
    store = ProvenanceStore("ahdt")
    ids = await run_scenario(store)
    rec = ProvenanceRecorder(store)
    extra = rec.observation("obs-extra", hdt_id=HDT, field_name="temperature", twin="whole_body")
    other = new_output_id()
    rec.model_run(other, "ahdt.whole_body.early_warning", "1.0.0", hdt_id=HDT, used=[extra])
    assert set(CausalGraphBuilder(store).build(other).nodes) == {
        f"atra:{other}", "atra:obs-extra"}
    assert "atra:obs-extra" not in CausalGraphBuilder(store).build(ids["wb"]).nodes


async def test_contract_and_graph_store(scenario):
    store, ids = scenario
    g = CausalGraphBuilder(store).build(ids["endo"])
    data = g.to_contract()
    assert {n.kind for n in data.nodes} == {"model", "message", "observation"}
    backend = NetworkXGraph()
    assert await persist(g, backend) == len(g.edges)
    rows = await backend.run("MATCH (a:ExplanationNode {id: $a}) RETURN a", {"a": g.root})
    assert rows and rows[0]["a"]["kind"] == "model"


async def test_unknown_output():
    with pytest.raises(KeyError):
        CausalGraphBuilder(ProvenanceStore("ahdt")).build("out-missing")
