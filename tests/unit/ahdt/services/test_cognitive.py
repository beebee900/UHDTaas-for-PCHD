import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from atra import contracts as c
from atra.service import Problem
from tests.contract.fixtures import HDT, T0, _obs


async def test_converse_keeps_the_session_and_remembers_the_language(services, runtime):
    first = await services.cognitive.converse(c.ConverseArgs(
        hdt_id=HDT, utterance="How am I?", language="yo"), None)
    c.ConverseData.model_validate({k: v for k, v in first.items() if k != "_meta"})
    assert first["reply"] and first["language"] == "yo" and first["grounded_on"]
    second = await services.cognitive.converse(c.ConverseArgs(
        hdt_id=HDT, utterance="And now?", language="en", session_id=first["session_id"]), None)
    assert second["session_id"] == first["session_id"]
    stored = await runtime.backends.cache.get(f"ahdt:session:{HDT}:{first['session_id']}")
    assert [t["role"] for t in stored] == ["user", "assistant", "user", "assistant"]
    assert runtime.languages[HDT] == "en"


async def test_perceive_text_finds_affirmed_findings_only(services):
    body = await services.cognitive.perceive(c.PerceiveArgs(
        hdt_id=HDT, modality="text", text="Patient has fever. Denies headache."), None)
    c.PerceiveData.model_validate(body)
    names = {f["display"] for f in body["findings"]}
    assert "Fever" in names and "Headache" not in names


async def test_perceive_signal_derives_heart_rate_and_ingests_it(services, runtime):
    import neurokit2 as nk

    pipe = await runtime.pipeline()
    ecg = nk.ecg_simulate(duration=20, sampling_rate=250, heart_rate=72, random_state=3)
    pipe.waveforms.append(HDT, "MDC_ECG_ELEC_POTL_II", datetime.now(UTC), ecg.tolist(), 4.0)
    body = await services.cognitive.perceive(c.PerceiveArgs(
        hdt_id=HDT, modality="signal", content_ref="MDC_ECG_ELEC_POTL_II"), None)
    c.PerceiveData.model_validate(body)
    hr = next(f for f in body["findings"] if f["code"] == "8867-4")
    assert hr["value"] == pytest.approx(72, abs=4) and 0 <= hr["confidence"] <= 1


async def test_perceive_refuses_what_it_cannot_read(services):
    with pytest.raises(Problem) as exc:
        await services.cognitive.perceive(c.PerceiveArgs(
            hdt_id=HDT, modality="signal", content_ref="MDC_ECG_ELEC_POTL_II"), None)
    assert exc.value.status == 404
    with pytest.raises(Problem) as exc:
        await services.cognitive.perceive(c.PerceiveArgs(hdt_id=HDT, modality="image"), None)
    assert exc.value.status == 501


async def test_reason_ontology_answers_with_a_path(services):
    body = await services.cognitive.reason(c.ReasonArgs(
        hdt_id=HDT, kind="ontology", query="Is fever a phenotypic abnormality?"), None)
    c.ReasonData.model_validate(body)
    assert body["answer"] == "yes" and "is_a*" in body["justification"][0]
    body = await services.cognitive.reason(c.ReasonArgs(
        hdt_id=HDT, kind="ontology", query="Is fever a Gizmo?"), None)
    assert body["answer"] == "unknown"


async def test_reason_temporal_names_the_allen_relation(services):
    body = await services.cognitive.reason(c.ReasonArgs(
        hdt_id=HDT, kind="temporal",
        query="Relation between malaria and artemether and lumefantrine"), None)
    assert body["answer"] == "overlapped by" or body["answer"] in {"starts", "overlaps",
                                                                    "during", "contains",
                                                                    "started by"}


async def test_reason_probabilistic_uses_the_forecast_distribution(services):
    body = await services.cognitive.reason(c.ReasonArgs(
        hdt_id=HDT, kind="probabilistic",
        query="Probability that temperature is above 30 within 6 hours"), None)
    assert float(body["answer"]) > 0.99
    body = await services.cognitive.reason(c.ReasonArgs(
        hdt_id=HDT, kind="probabilistic",
        query="Probability that temperature is above 60 within 6 hours"), None)
    assert float(body["answer"]) < 0.01


async def test_reason_causal_lists_the_contributing_inputs(services, state_output):
    body = await services.cognitive.reason(c.ReasonArgs(
        hdt_id=HDT, kind="causal", query=f"Why did {state_output} change?"), None)
    assert body["answer"].endswith(")") or "contributed" in body["answer"]
    assert body["justification"]


async def test_request_data_is_sent_and_answered_when_the_data_arrives(services, runtime):
    args = c.RequestDataArgs.model_validate(
        {"hdt_id": HDT, "what": ["15074-8"], "from": "person", "channel": "sms",
         "deadline_h": 1})
    sent = []
    runtime.backends.events.subscribe("notification.*", lambda e: sent.append(e) or _done())
    body = await services.cognitive.request_data(args, None)
    c.RequestDataData.model_validate(body)
    assert body["status"] == "queued"
    await _until(lambda: sent)
    assert sent[0].payload["channel"] == "sms" and sent[0].payload["what"] == ["15074-8"]
    pipe = await runtime.pipeline()
    await pipe.process([_obs(902, "15074-8", 95.0, "mg/dL", T0 + timedelta(hours=60))])
    status = await runtime.backends.workflows.result(body["request_id"], timeout_s=10)
    assert status == "answered"


async def _done():
    return None


async def _until(check, timeout=5.0):
    for _ in range(int(timeout / 0.05)):
        if check():
            return
        await asyncio.sleep(0.05)
    raise AssertionError("condition not met")
