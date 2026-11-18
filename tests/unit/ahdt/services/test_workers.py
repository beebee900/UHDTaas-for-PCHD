import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from ahdt.services import voi
from ahdt.services.filters import ukf_assimilate
from ahdt.services.lifecycle import PSI_LIMIT, DriftMonitor, psi
from ahdt.services.outputs import StoredOutput
from ahdt.workers import calibration, reminders
from atra import contracts as c
from atra.connectors import DTKind
from atra.consent import PatientConsent
from tests.contract.fixtures import HDT, T0, _obs
from tests.unit.ahdt.services.test_model import KIDNEY


async def test_a_reading_beyond_the_limits_refreshes_and_explains_the_twin(app, services,
                                                                          runtime):
    pipe = await runtime.pipeline()
    await pipe.process([_obs(950, "8867-4", 185.0, "/min", T0 + timedelta(hours=50))])
    await runtime.backends.events.drain()
    rows = pipe.lake.query("SELECT output_id FROM outputs", table="outputs")
    assert rows
    explained = [e for r in rows for e in await services.xai.store.for_output(r["output_id"])]
    assert explained and explained[0].trigger == "severity:alert"


async def test_a_normal_reading_does_not_start_an_explanation(services, runtime):
    pipe = await runtime.pipeline()
    await pipe.process([_obs(951, "8867-4", 70.0, "/min", T0 + timedelta(hours=50))])
    await runtime.backends.events.drain()
    assert pipe.lake.query("SELECT output_id FROM outputs", table="outputs") == []


async def test_the_cooldown_limits_refreshes(app, runtime):
    from ahdt.workers.auto_explain import AutoExplainWorker

    calls = []

    class Spy:
        runtime = app.state.runtime

        def __init__(self):
            self.model = self

        reference_range = staticmethod(app.state.services.model.reference_range)

        async def state_of(self, hdt_id, kind):
            calls.append((hdt_id, kind))

    now = [0.0]
    worker = AutoExplainWorker(Spy(), cooldown_s=100, clock=lambda: now[0])
    from atra.contracts import EventEnvelope

    def event(i):
        return EventEnvelope(event_id=f"e{i}", event_type="observation.ingested", source="x",
                             hdt_id=HDT, wall_time=T0, trace_id="t",
                             payload={"dt": "cardiovascular", "field": "heart_rate",
                                      "value": 200.0})

    await worker.handle(event(1))
    await worker.handle(event(2))
    now[0] = 150.0
    await worker.handle(event(3))
    assert len(calls) == 2


async def test_nightly_calibration_runs_each_round_and_writes_revisions(services, runtime):
    pipe = await runtime.pipeline()
    code = next(iter(runtime.catalogue[KIDNEY].spec.obs_map))
    await pipe.process([_obs(i, code, 90.0 + i, "umol/L", T0 + timedelta(hours=6 * i))
                        for i in range(4)])
    workflows = runtime.backends.workflows
    calibration.register(workflows, services)
    run = await calibration.start(workflows, [HDT], interval_h=0.0, rounds=1)
    assert await workflows.result(run, timeout_s=120) == 1
    record = await runtime.store.get(HDT, runtime.catalogue[KIDNEY].spec.instances[0])
    assert record.revision >= 1 and record.last_assimilated is not None


async def test_calibrate_all_reports_why_a_model_was_skipped(services):
    done = await services.model.calibrate_all(HDT)
    skipped = [d for d in done if "skipped" in d]
    assert skipped and all(isinstance(d["skipped"], str) for d in skipped)


async def test_a_reminder_is_sent_only_with_consent(runtime):
    workflows = runtime.backends.workflows
    reminders.register(workflows, runtime.notifier)
    sent = []
    runtime.backends.events.subscribe("notification.*",
                                      lambda e: sent.append(e) or asyncio.sleep(0))
    ok = await workflows.start("reminder", {"hdt_id": HDT, "text": "Take your tablets",
                                            "delay_h": 0.0, "channel": "sms"})
    assert await workflows.result(ok, timeout_s=10) == "sms"
    runtime.consents.set(HDT, PatientConsent({"public_health"}, set()))
    withheld = await workflows.start("reminder", {"hdt_id": HDT, "text": "x", "delay_h": 0.0})
    assert await workflows.result(withheld, timeout_s=10) == "withheld"
    assert [e.payload["text"] for e in sent] == ["Take your tablets"]


async def test_a_questionnaire_sends_at_each_hour(runtime):
    workflows = runtime.backends.workflows
    reminders.register(workflows, runtime.notifier)
    run = await workflows.start("questionnaire", {"hdt_id": HDT, "instrument": "phq9",
                                                  "at_h": [0.0, 0.0]})
    assert await workflows.result(run, timeout_s=10) == ["app", "app"]


async def test_voi_ranks_stale_fields_per_unit_of_burden(runtime):
    now = T0 + timedelta(hours=40)
    ranked = await voi.rank(runtime, HDT, [DTKind.CARDIOVASCULAR, DTKind.ENDOCRINE], now=now)
    names = [a.field for a in ranked]
    assert "glucose" in names and "heart_rate" in names
    glucose = next(a for a in ranked if a.field == "glucose")
    assert 0 < glucose.staleness <= 1 and glucose.voi == pytest.approx(
        glucose.staleness / glucose.burden)
    assert [a.voi for a in ranked] == sorted((a.voi for a in ranked), reverse=True)
    fresh = await voi.rank(runtime, HDT, [DTKind.CARDIOVASCULAR], now=T0 + timedelta(hours=35))
    assert all(a.field != "heart_rate" or a.staleness == 1.0 for a in fresh)


def test_psi_is_large_for_a_shifted_distribution():
    ref = [float(i % 10) for i in range(200)]
    assert psi(ref, ref) == pytest.approx(0.0, abs=1e-6)
    assert psi(ref, [x + 6 for x in ref]) > PSI_LIMIT


async def test_drift_between_weeks_publishes_an_event(runtime):
    pipe = await runtime.pipeline()
    now = datetime.now(UTC)
    for week, base in ((10, 5.0), (3, 12.0)):
        for i in range(12):
            when = now - timedelta(days=week) + timedelta(hours=i)
            out = StoredOutput(f"out-{week}-{i}", "ahdt.test.model", "1.0.0", HDT, "state",
                               "cardiovascular", {"cardiac_output": base + i * 0.01},
                               created_at=when)
            pipe.lake.append("outputs", [{"output_id": out.output_id, "hdt_id": HDT,
                                          "model_id": out.model_id, "version": out.version,
                                          "body": out.body(), "ingested_at": when}])
    seen = []
    runtime.backends.events.subscribe("model.drift_detected",
                                      lambda e: seen.append(e) or asyncio.sleep(0))
    drifted = await DriftMonitor(runtime).check("ahdt.test.model", now=now)
    await runtime.backends.events.drain()
    assert [d.output for d in drifted] == ["cardiac_output"]
    assert seen[0].payload["model_id"] == "ahdt.test.model"
    assert await DriftMonitor(runtime).check("ahdt.unknown.model", now=now) == []


async def test_ukf_filters_creatinine_towards_the_observations(runtime):
    model = runtime.catalogue[KIDNEY]
    await runtime.ensure(HDT, model.spec.instances)
    record = await runtime.store.get(HDT, model.spec.instances[0])
    code = next(iter(model.spec.obs_map))
    start = datetime(2026, 10, 1, tzinfo=UTC)
    base = record.state["creatinine"]

    records = [c.ObservationRecord(
        record_id=f"u{i}", hdt_id=HDT, dt=DTKind.RENAL_URINARY,
        code=c.Code(system="http://loinc.org", code=code), value=base * 1.5, unit="umol/L",
        effective_time=start + timedelta(hours=6 * (i + 1)), source="device",
        consent_tag="care", provenance_id="atra:x") for i in range(4)]
    fitted = ukf_assimilate(model, record.model_copy(update={"last_assimilated": start}),
                            records)
    assert fitted.state["creatinine"] > base
    assert fitted.uncertainty["creatinine"]["std"] > 0
    assert fitted.last_assimilated == records[-1].effective_time
