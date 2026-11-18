"""The APDT's episode list, patient directory, intake, consent read and audit page."""

from atra import contracts as c
from atra.personas import BY_KEY
from tests.contract.test_apdt_clinical import (  # noqa: F401
    BASE,
    decision,
    h,
    http,
    make_twins,
    tok,
)

FAC_A = BASE.format(tenant="fac-a")


async def test_episode_list_is_scoped_to_the_caller(make_twins):  # noqa: F811
    twins = await make_twins("ao", "bm")
    ao, bm = BY_KEY["ao"], BY_KEY["bm"]
    async with http(twins.apdt) as cl:
        staff = (await cl.get(f"{FAC_A}/episodes", headers=twins.mo())).json()
        patient = h(tok(twins.apdt, "patient", hdt_id=ao.hdt_id))
        own = (await cl.get(f"{FAC_A}/episodes", params={"hdt_id": ao.hdt_id},
                            headers=patient)).json()
        unnamed = await cl.get(f"{FAC_A}/episodes", headers=patient)
        proxy = h(tok(twins.apdt, "proxy", proxy_for=[bm.hdt_id]))
        by_proxy = (await cl.get(f"{FAC_A}/episodes", params={"hdt_id": bm.hdt_id},
                                 headers=proxy)).json()
        other = await cl.get(f"{FAC_A}/episodes/{twins.episode('ao')}", headers=proxy)
        fac_b = await cl.get(f"{FAC_A}/episodes", headers=twins.mo("fac-b"))
    items = [c.EpisodeListItem.model_validate(x) for x in staff]
    assert {i.episode.hdt_id for i in items} == {ao.hdt_id, bm.hdt_id}
    assert {i.patient.initials for i in items if i.patient} == {"A.O.", "B.M."}
    assert [x["episode"]["hdt_id"] for x in own] == [ao.hdt_id]
    assert unnamed.status_code == 403
    assert [x["episode"]["hdt_id"] for x in by_proxy] == [bm.hdt_id]
    assert other.status_code == 403
    assert fac_b.status_code == 403


async def test_a_new_episode_with_an_intake_gets_recommendations(make_twins):  # noqa: F811
    twins = await make_twins("bm")
    ao = BY_KEY["ao"]
    async with http(twins.apdt) as cl:
        patients = (await cl.get(f"{FAC_A}/patients", headers=twins.mo())).json()
        catalogue = c.IntakeCatalogue.model_validate(
            (await cl.get(f"{FAC_A}/intake/catalogue", headers=twins.mo())).json())
        r = await cl.post(f"{FAC_A}/episodes", headers=twins.mo(),
                          json={"hdt_id": ao.hdt_id, "reason": "Fever for three days"})
        eid = r.json()["episode"]["episode_id"]
        bad = await cl.post(f"{FAC_A}/episodes/{eid}/intake", headers=twins.mo(),
                            json={"findings": {"find.not_a_finding": True}})
        intake = await cl.post(f"{FAC_A}/episodes/{eid}/intake", headers=twins.mo(), json={
            "findings": {"find.fever_history": True}, "tests": {"test.malaria_rdt_hrp2": True},
            "measurements": {"temperature": 38.6}, "weight_kg": 62})
        recs = (await cl.get(f"{FAC_A}/episodes/{eid}/recommendations",
                             headers=twins.mo())).json()
    assert {p["initials"] for p in patients} == {"A.O.", "B.M.", "C.N.", "E.F."}
    assert "find.fever_history" in {f.id for f in catalogue.findings}
    assert "test.malaria_rdt_hrp2" in {t.id for t in catalogue.tests}
    assert {m.field: m.unit for m in catalogue.measurements}["temperature"] == "Cel"
    assert bad.status_code == 422
    assert intake.status_code == 201 and intake.json()["resources"]
    top = next(x for x in recs if x["kind"] == "diagnosis")
    assert top["payload"]["condition"] == "cond.malaria_falciparum"


async def test_consent_reads_and_the_audit_is_newest_first(make_twins):  # noqa: F811
    twins = await make_twins("ao")
    ao, gh = BY_KEY["ao"], BY_KEY["gh"]
    async with http(twins.apdt) as cl:
        own = await cl.get(f"{FAC_A}/patients/{ao.hdt_id}/consent", headers=h(tok(
            twins.apdt, "patient", hdt_id=ao.hdt_id)))
        withheld = await cl.get(f"{BASE.format(tenant='fac-b')}/patients/{gh.hdt_id}/consent",
                                headers=twins.mo("fac-b"))
        audit = (await cl.get(f"{FAC_A}/audit", params={"limit": 3, "hdt_id": ao.hdt_id},
                              headers=twins.mo())).json()
    assert own.status_code == 200 and "care" in own.json()["purposes"]
    assert withheld.json()["refused_tools"] == ["ahdt.data.genome"]
    assert len(audit) == 3 and all(a["hdt_id"] == ao.hdt_id for a in audit)
    assert [a["seq"] for a in audit] == sorted((a["seq"] for a in audit), reverse=True)


async def test_the_pharmacist_continues_the_run_the_medical_officer_signed(make_twins):  # noqa: F811
    twins = await make_twins("ao")
    ph = h(tok(twins.apdt, "pharmacist"))
    goal = f"{FAC_A}/episodes/{twins.episode('ao')}/goals/treatment"
    async with http(twins.apdt) as cl:
        first = (await cl.post(goal, headers=twins.mo())).json()["run_id"]
        again = (await cl.post(goal, headers=twins.mo())).json()["run_id"]
        run = (await cl.get(f"{FAC_A}/runs/{first}", headers=twins.mo())).json()
        rec_id = run["interrupt"]["payload"]["recommendation_id"]
        signed = await cl.post(f"{FAC_A}/runs/{first}/resume", headers=twins.mo(),
                               json=decision(rec_id, "sign"))
        by_pharmacist = (await cl.post(goal, headers=ph)).json()["run_id"]
        waiting = (await cl.get(f"{FAC_A}/runs/{by_pharmacist}", headers=ph)).json()
    assert again == first and by_pharmacist == first
    assert run["interrupt"]["kind"] == "sign_prescription"
    assert signed.status_code == 200
    assert waiting["interrupt"]["kind"] == "verify_prescription"
    assert waiting["interrupt"]["required_role"] == "pharmacist"
