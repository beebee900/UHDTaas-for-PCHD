from datetime import UTC, datetime

import pytest
from sqlalchemy import update

from apdt.records.activity import ActivityLog
from apdt.records.agency import AgencyRecord
from apdt.records.episodes import EpisodeRecord
from apdt.records.reasoning import ReasoningRecord
from apdt.records.tables import create_all, reasoning_log
from apdt.records.view_cache import AhdtViewCache
from atra.backends.memory import DyonEventBus, MemoryCache, MemoryFhir, SqliteRelational
from atra.contracts import ClinicalDecision, Decider, Recommendation
from atra.provenance import ChainBroken

HDT = "hdt-0123456789ab"


@pytest.fixture
async def db(tmp_path):
    db = SqliteRelational(tmp_path / "apdt.sqlite")
    await create_all(db)
    yield db
    await db.close()


async def test_episode_holds_its_resources_per_tenant():
    fhir = MemoryFhir()
    a, b = EpisodeRecord(fhir, "fac-a"), EpisodeRecord(fhir, "fac-b")
    ep = await a.open(HDT, reason="fever", at=datetime(2026, 10, 10, tzinfo=UTC))
    assert ep["id"] == "ep-2026-000001"
    await a.add(ep["id"], {"resourceType": "Encounter", "status": "in-progress",
                           "class": {"code": "AMB"}})
    await a.add(ep["id"], {"resourceType": "Condition", "code": {"text": "malaria"}})
    assert len(await a.resources(ep["id"])) == 2
    assert await b.episodes_of(HDT) == []
    with pytest.raises(ValueError):
        await a.add(ep["id"], {"resourceType": "Patient"})
    await a.close(ep["id"])
    with pytest.raises(ValueError):
        await a.add(ep["id"], {"resourceType": "Condition"})
    assert (await a.open(HDT))["id"] == "ep-2026-000002"


async def test_reasoning_chain_verifies_and_detects_tampering(db):
    rr = ReasoningRecord(db, "fac-a")
    rec = Recommendation(recommendation_id="rec-1", episode_id="ep-2026-000001", hdt_id=HDT,
                         kind="diagnosis", payload={"top": "cond.malaria_falciparum"},
                         confidence=0.8, status="proposed", autonomy_level="recommend",
                         created_by_agent="diagnostic")
    await rr.recommendation(rec)
    decider = Decider(role="medical_officer", id="fac-a-medical_officer-1")
    with pytest.raises(ValueError, match="reason"):
        await rr.decision(ClinicalDecision(decision_id="d-1", recommendation_id="rec-1",
                                           decided_by=decider, decision="reject", signature="s"),
                          episode_id="ep-2026-000001", hdt_id=HDT)
    await rr.decision(ClinicalDecision(decision_id="d-1", recommendation_id="rec-1",
                                       decided_by=decider, decision="reject",
                                       override_reason="RDT negative", signature="s"),
                      episode_id="ep-2026-000001", hdt_id=HDT)
    assert await ReasoningRecord(db, "fac-b").verify() == 0
    assert await rr.verify() == 2
    async with db.engine().begin() as conn:
        await conn.execute(update(reasoning_log).where(reasoning_log.c.seq == 0)
                           .values(body={"top": "forged"}))
    with pytest.raises(ChainBroken):
        await rr.verify()


async def test_view_cache_fetches_once_and_notes_the_view(db):
    rr = ReasoningRecord(db, "fac-a")
    cache = AhdtViewCache(MemoryCache(), rr)
    calls = []

    async def fetch():
        calls.append(1)
        return {"hb": 9.1, "_meta": {"models": [{"model_id": "m", "version": "1"}]}}

    for _ in range(2):
        view = await cache.get(hdt_id=HDT, episode_id="ep-2026-000001", tool="ahdt.data.state",
                               args={"twin": "haematological"}, fetch=fetch)
    assert view["hb"] == 9.1 and len(calls) == 1
    noted = await rr.entries(kind="ahdt_view")
    assert len(noted) == 1 and noted[0]["body"]["ahdt_models"][0]["model_id"] == "m"
    assert await cache.invalidate(HDT) == 1


async def test_agency_weights_questions_and_fhir(db):
    ag = AgencyRecord(MemoryFhir(), db, "fac-a")
    await ag.set_weights(HDT, {"effectiveness": 3, "cost": 1}, method="swing")
    assert await ag.weights(HDT) == {"effectiveness": 0.75, "cost": 0.25}
    qid = await ag.ask(HDT, "Can I keep working?", channel="sms")
    assert len(await ag.questions(HDT, open_only=True)) == 1
    await ag.answer(qid, "Yes, after the fever settles.")
    assert await ag.questions(HDT, open_only=True) == []
    await ag.goal(HDT, "Back at work within a week")
    await ag.proxy(HDT, "Ada", "MTH")
    await ag.consent(HDT, ["care", "self_management"])
    await ag.answers(HDT, "preferences", {"language": "yo", "budget_ngn": 5000})
    for rtype in ("Goal", "RelatedPerson", "Consent", "QuestionnaireResponse"):
        assert len(await ag.resources(HDT, rtype)) == 1, rtype


async def test_activity_publishes_every_change(db):
    bus = DyonEventBus()
    log = ActivityLog(db, bus, "fac-a")
    alert = await log.alert(severity="high", reason="NEWS2 7", to_role="nurse", to_id=None,
                            hdt_id=HDT, episode_id="ep-2026-000001")
    await log.escalate(alert["activity_id"], to_role="medical_officer", to_id="mo-1", level=1)
    await log.acknowledge(alert["activity_id"], by="mo-1")
    task = await log.task("Repeat RDT", hdt_id=HDT, episode_id="ep-2026-000001", to_role="lab")
    assert [i["activity_id"] for i in await log.open_items()] == [task["activity_id"]]
    await log.complete(task["activity_id"], by="lab-1")
    assert [e.event_type for e in bus.published] == [
        "alert.raised", "alert.escalated", "alert.acknowledged", "task.created", "task.completed"]
