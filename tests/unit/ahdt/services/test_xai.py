from datetime import timedelta

import pytest

from atra import contracts as c
from atra.service import Problem
from tests.contract.fixtures import HDT, T0, _obs


async def explain(services, output_id, audience="clinician"):
    return await services.xai.explain(
        c.ExplainArgs(hdt_id=HDT, output_id=output_id, audience=audience), None)


async def test_explain_returns_a_contract_explanation_and_stores_it(services, state_output):
    body = await explain(services, state_output)
    c.AHDTExplanation.model_validate({k: v for k, v in body.items() if k != "_meta"})
    assert body["output_id"] == state_output and body["drivers"]
    stored = await services.xai.store.get(body["explanation_id"])
    assert stored is not None and stored.explanation.text == body["text"]
    again = await explain(services, state_output)
    assert again["explanation_id"] == body["explanation_id"]


async def test_the_patient_text_is_localised_or_falls_back_to_english(services, state_output):
    body = await explain(services, state_output, "patient")
    assert body["text"]
    assert [e.audience for e in await services.xai.store.for_output(state_output)] \
        == ["patient"]


async def test_unknown_or_foreign_outputs_are_not_found(services):
    with pytest.raises(Problem) as exc:
        await explain(services, "out-0199b1c2-0000-7000-8000-000000000001")
    assert exc.value.status == 404


async def test_causal_graph_links_the_output_to_its_observations(services, state_output):
    body = await services.xai.causal_graph(
        c.CausalGraphArgs(hdt_id=HDT, output_id=state_output), None)
    c.CausalGraphData.model_validate(body)
    kinds = {n["kind"] for n in body["nodes"]}
    assert kinds == {"model", "observation"}
    assert all(e["to"] == f"atra:{state_output}" for e in body["edges"])


async def test_attributions_become_edge_weights(services, state_output):
    await explain(services, state_output)
    body = await services.xai.causal_graph(
        c.CausalGraphArgs(hdt_id=HDT, output_id=state_output), None)
    assert body["edges"] and any(e["weight"] != 1.0 for e in body["edges"])


async def test_forecast_outputs_are_explained(services):
    out = await services.model.forecast(c.ForecastArgs(
        hdt_id=HDT, dt="immune_lymphatic", variable="temperature", horizon_h=12), None)
    body = await explain(services, out["output_id"])
    assert body["method_family"] == "temporal_attribution"


async def test_a_state_above_watch_is_explained_without_a_request(services, runtime):
    pipe = await runtime.pipeline()
    await pipe.process([_obs(901, "8867-4", 180.0, "/min", T0 + timedelta(hours=40))])
    body = await services.model.state(c.StateArgs(hdt_id=HDT, dt="cardiovascular"), None)
    assert body["status"] == "alert"
    stored = await services.xai.store.for_output(body["output_id"])
    assert len(stored) == 1 and stored[0].trigger == "severity:alert"


async def test_a_normal_state_is_not_explained(services, state_output):
    assert await services.xai.store.for_output(state_output) == []
