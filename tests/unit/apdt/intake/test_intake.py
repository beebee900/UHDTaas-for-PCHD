"""Questionnaire service ($populate, $extract, renderer data) and the scribing pipeline."""

from datetime import UTC, datetime, timedelta

import pytest
from dyon.intelligent.offline_llm import OfflineChatModel

from apdt.intake import questionnaires as qs
from apdt.intake import scribe
from apdt.records.episodes import PATIENT_SYSTEM
from atra.personas import BY_KEY

HDT = BY_KEY["ao"].hdt_id
SUBJECT = {"identifier": {"system": PATIENT_SYSTEM, "value": HDT}}
NOW = datetime(2026, 10, 2, 9, 0, tzinfo=UTC)
COUGH = {"system": "http://snomed.info/sct", "code": "49727002"}


def finding(code, value, when, status="final"):
    return {"resourceType": "Observation", "id": f"o-{when:%d%H}", "status": status,
            "code": {"coding": [code]}, "subject": SUBJECT,
            "effectiveDateTime": when.isoformat(), "valueBoolean": value}


def history():
    q = qs.served(qs.load("history-acute-febrile"))
    item = next(i for i in q["item"] if i["linkId"] == "find.cough")
    assert item["code"][0]["code"] == COUGH["code"]
    return q


def test_served_marks_coded_items_only():
    q = history()
    exts = {i["linkId"]: [e["url"] for e in i.get("extension", [])] for i in q["item"]}
    assert qs.EXTRACT in exts["find.cough"] and qs.LINK_PERIOD in exts["find.cough"]
    assert exts["onset_days"] == []


def test_populate_uses_the_latest_usable_observation_in_the_period():
    obs = [finding(COUGH, False, NOW - timedelta(days=3)),
           finding(COUGH, True, NOW - timedelta(days=1)),
           finding(COUGH, False, NOW - timedelta(hours=2), status="preliminary"),
           finding(COUGH, False, NOW - timedelta(days=30))]
    qr = qs.populate(history(), SUBJECT, obs, now=NOW)
    assert qr["status"] == "in-progress"
    assert qr["item"] == [{"linkId": "find.cough", "text": "Cough?",
                           "answer": [{"valueBoolean": True}]}]


def test_extract_makes_observations_of_coded_answers():
    qr = {"resourceType": "QuestionnaireResponse", "id": "qr-1", "status": "completed",
          "subject": SUBJECT, "authored": NOW.isoformat(),
          "item": [{"linkId": "onset_days", "answer": [{"valueInteger": 2}]},
                   {"linkId": "find.cough", "answer": [{"valueBoolean": False}]},
                   {"linkId": "find.fever_history", "answer": [{"valueBoolean": True}]}]}
    out = qs.extract(history(), qr)
    assert {o["code"]["coding"][0]["code"]: o["valueBoolean"] for o in out} == {
        COUGH["code"]: False, next(i for i in history()["item"]
                                   if i["linkId"] == "find.fever_history")["code"][0]["code"]:
        True}
    assert all(o["derivedFrom"] == [{"reference": "QuestionnaireResponse/qr-1"}] for o in out)
    assert all(o["subject"] == SUBJECT and o["effectiveDateTime"] for o in out)
    with pytest.raises(ValueError):
        qs.extract(history(), {**qr, "status": "in-progress"})
    assert qs.extract(qs.load("history-acute-febrile"), qr) == []


def test_render_flattens_groups_with_options():
    data = qs.render(qs.load("check-in"))
    rows = {r["linkId"]: r for r in data["items"]}
    assert rows["overall"]["options"][0] == {"code": "better", "display": "Better"}
    assert rows["find.vomiting"]["depth"] == 1 and rows["find.vomiting"]["parent"] == \
        "danger_signs"


class FakeTranscriber:
    async def transcribe(self, audio: bytes, content_type: str) -> str:
        return ("Patient reports fever for two days. No cough. She took paracetamol. "
                "On examination she is warm.")


SOAP = ('{"subjective": "Fever for two days. Cough.", "objective": "Warm to touch.", '
        '"assessment": "Possible malaria.", "plan": "Malaria RDT. Give amoxicillin."}')


async def test_scribe_drafts_a_composition_and_flags_negation_mismatch():
    pipeline = scribe.ScribePipeline(FakeTranscriber(), OfflineChatModel(responder=lambda p: SOAP))
    draft = await pipeline.draft(b"\0\0", "audio/wav", hdt_id=HDT, episode_id="ep-2026-000001",
                                 author="medical_officer.fac-a", recording_consented=True,
                                 at=NOW)
    comp = draft.composition
    assert comp["status"] == "preliminary" and comp["type"]["coding"][0]["code"] == "11488-4"
    assert [s["code"]["coding"][0]["code"] for s in comp["section"]] == [
        "61150-9", "61149-1", "51848-0", "18776-5"]
    assert {(i.kind, i.ref, i.section) for i in draft.issues} == {
        ("negation_mismatch", "find.cough", "subjective"),
        ("not_in_transcript", "J01CA04", "plan")}
    with pytest.raises(scribe.ScribeRefused):
        scribe.sign(comp, clinician="medical_officer.fac-a", at=NOW, issues_reviewed=False)
    signed = scribe.sign(comp, clinician="medical_officer.fac-a", at=NOW, issues_reviewed=True)
    assert signed["status"] == "final" and signed["attester"][0]["mode"] == "legal"


async def test_scribe_needs_recording_consent_and_checks_english_only():
    pipeline = scribe.ScribePipeline(FakeTranscriber(), OfflineChatModel(responder=lambda p: SOAP))
    with pytest.raises(scribe.ScribeRefused):
        await pipeline.draft(b"", "audio/wav", hdt_id=HDT, episode_id="ep-2026-000001",
                             author="mo", recording_consented=False)
    draft = await pipeline.draft(b"", "audio/wav", hdt_id=HDT, episode_id="ep-2026-000001",
                                 author="mo", language="yo", recording_consented=True)
    assert not draft.checked and draft.issues == [] and draft.composition["language"] == "yo"


async def test_scribe_keeps_empty_sections_out_when_the_llm_reply_is_not_json():
    pipeline = scribe.ScribePipeline(FakeTranscriber(),
                                     OfflineChatModel(responder=lambda p: "I cannot help."))
    draft = await pipeline.draft(b"", "audio/wav", hdt_id=HDT, episode_id="ep-2026-000001",
                                 author="mo", recording_consented=True)
    assert "section" not in draft.composition and all(not v for v in draft.sections.values())
