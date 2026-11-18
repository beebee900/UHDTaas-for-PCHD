from datetime import timedelta

import pytest

from atra import contracts as c
from atra.connectors import DTKind
from atra.service import Problem
from tests.contract.fixtures import HDT, SCENARIO, T0, _obs

KIDNEY = "ahdt.renal_urinary.kidney_and_renal_function"


async def revisions(runtime):
    return {a: (await runtime.store.get(HDT, a)).revision for a in runtime.store.instances(HDT)}


async def assert_live_unchanged(runtime, before):
    """Instances that existed keep their revision; instances created for the fork start at 0."""
    after = await revisions(runtime)
    assert {a: after[a] for a in before} == before
    assert all(r == 0 for a, r in after.items() if a not in before)


async def test_state_merges_instances_and_observed_fields(services):
    body = await services.model.state(c.StateArgs(hdt_id=HDT, dt="cardiovascular"), None)
    c.StateData.model_validate({k: v for k, v in body.items() if k != "_meta"})
    assert body["state"]["heart_rate"] == pytest.approx(104.0 - 0.3 * 35 + 35 % 4)
    assert "cardiac_output" in body["state"]
    assert body["status"] in ("normal", "watch", "alert")
    assert body["_meta"]["output_id"] == body["output_id"]


async def test_state_status_follows_the_reference_ranges(services, runtime):
    pipe = await runtime.pipeline()
    await pipe.process([_obs(900, "8867-4", 180.0, "/min", T0 + timedelta(hours=40))])
    body = await services.model.state(c.StateArgs(hdt_id=HDT, dt="cardiovascular"), None)
    assert body["status"] == "alert"


async def test_state_of_a_twin_without_a_model_reports_observations(services):
    body = await services.model.state(c.StateArgs(hdt_id=HDT, dt="behavioural_cognitive"), None)
    assert body["status"] == "normal" and body["state"] == {}


async def test_forecast_projects_the_series_with_a_band(services):
    args = c.ForecastArgs(hdt_id=HDT, dt="immune_lymphatic", variable="temperature",
                          horizon_h=24)
    body = await services.model.forecast(args, None)
    c.ForecastData.model_validate({k: v for k, v in body.items() if k != "_meta"})
    assert body["t"][0] == 0 and body["t"][-1] == pytest.approx(24, abs=1.5)
    assert all(lo <= m <= hi for lo, m, hi in zip(body["lower"], body["mean"], body["upper"],
                                                    strict=True))
    assert body["upper"][-1] - body["lower"][-1] > 0


async def test_forecast_refuses_a_short_series_and_unknown_field(services):
    with pytest.raises(Problem) as exc:
        await services.model.forecast(c.ForecastArgs(
            hdt_id=HDT, dt="cardiovascular", variable="bnp", horizon_h=6), None)
    assert exc.value.status == 409
    with pytest.raises(Problem) as exc:
        await services.model.forecast(c.ForecastArgs(
            hdt_id=HDT, dt="cardiovascular", variable="nonsense", horizon_h=6), None)
    assert exc.value.status == 422


async def test_facet_reads_the_shared_instance(services):
    args = c.FacetArgs(hdt_id=HDT, anatomy="UBERON:0001264", facet="endocrine")
    body = await services.model.facet(args, None)
    c.FacetView.model_validate(body)
    assert body["anatomy"] == "UBERON:0001264" and body["fields"]
    with pytest.raises(Problem) as exc:
        await services.model.facet(c.FacetArgs(hdt_id=HDT, anatomy="UBERON:0001264",
                                               facet="nope"), None)
    assert exc.value.status == 404


async def test_simulate_runs_on_a_fork_and_leaves_live_revisions_unchanged(services, runtime):
    await services.model.state(c.StateArgs(hdt_id=HDT, dt="renal_urinary"), None)
    before = await revisions(runtime)
    args = c.SimulateArgs(hdt_id=HDT, dt="renal_urinary", scenario=SCENARIO, horizon_h=12)
    body = await services.model.simulate(args, None)
    c.SimulateData.model_validate({k: v for k, v in body.items() if k != "_meta"})
    assert body["fork_id"] and body["_meta"]["forked"] is True
    assert body["t"][0] == 0 and body["t"][-1] == pytest.approx(12 * 3600)
    await assert_live_unchanged(runtime, before)
    assert runtime.store.forks() == {}


async def test_simulate_without_a_capable_model_is_refused(services):
    scenario = {**SCENARIO, "kind": "diet"}
    args = c.SimulateArgs(hdt_id=HDT, dt="behavioural_cognitive", scenario=scenario)
    with pytest.raises(Problem) as exc:
        await services.model.simulate(args, None)
    assert exc.value.status == 422


async def test_cosimulate_couples_the_members_on_forks(services, runtime):
    await services.model.state(c.StateArgs(hdt_id=HDT, dt="renal_urinary"), None)
    before = await revisions(runtime)
    args = c.CosimulateArgs(hdt_id=HDT, scenario=SCENARIO, dts=["renal_urinary", "hepatobiliary"],
                            horizon_h=12, step_s=1800)
    body = await services.model.cosimulate(args, None)
    c.SimulateData.model_validate({k: v for k, v in body.items() if k != "_meta"})
    assert len(body["t"]) == 25 and body["t"][0] == 0
    assert any(k.startswith("renal_urinary.") for k in body["series"])
    assert all(len(v) == len(body["t"]) for v in body["series"].values())
    await assert_live_unchanged(runtime, before)
    assert runtime.store.forks() == {}


async def test_calibrate_writes_through_the_assimilation_writer(services, runtime):
    pipe = await runtime.pipeline()
    model = runtime.catalogue[KIDNEY]
    code = next(iter(model.spec.obs_map))
    await pipe.process([_obs(i, code, 90.0 + i, "umol/L", T0 + timedelta(hours=i * 6))
                        for i in range(4)])
    args = c.CalibrateArgs(hdt_id=HDT, dt=DTKind.RENAL_URINARY, model_id=KIDNEY)
    body = await services.model.calibrate(args, None)
    c.CalibrateData.model_validate({k: v for k, v in body.items() if k != "_meta"})
    anatomy = model.spec.instances[0]
    record = await runtime.store.get(HDT, anatomy)
    assert record.revision == body["revision"] >= 1 and record.last_assimilated is not None
    assert body["fit_after"] <= body["fit_before"]


async def test_calibrate_needs_observations_and_a_matching_model(services):
    with pytest.raises(Problem) as exc:
        await services.model.calibrate(c.CalibrateArgs(
            hdt_id=HDT, dt=DTKind.RENAL_URINARY, model_id=KIDNEY), None)
    assert exc.value.status == 409
    with pytest.raises(Problem) as exc:
        await services.model.calibrate(c.CalibrateArgs(
            hdt_id=HDT, dt=DTKind.ENDOCRINE, model_id=KIDNEY), None)
    assert exc.value.status == 404
