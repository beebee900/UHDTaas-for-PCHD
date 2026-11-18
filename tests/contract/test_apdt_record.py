"""The clinical record: the diagnosis, dispense and care-given entries, and the follow-up work
they close."""

from atra import contracts as c
from tests.contract.test_apdt_api import EP, apdt, client, h, tok  # noqa: F401

BASE = f"/v1/t/fac-a/episodes/{EP}"


async def test_each_role_enters_its_own_part_of_the_record(apdt):  # noqa: F811
    mo, rph, rn = (h(tok(apdt, r)) for r in ("medical_officer", "pharmacist", "nurse"))
    async with client(apdt) as cl:
        diagnosis = await cl.post(f"{BASE}/record/diagnosis", headers=mo, json={
            "condition": "Uncomplicated falciparum malaria", "status": "confirmed",
            "basis": "Positive RDT and fever", "recommendation_id": "rec-1"})
        dispense = await cl.post(f"{BASE}/record/dispense", headers=rph, json={
            "medication": "Artemether-lumefantrine 20/120 mg", "dose": "4 tablets twice daily",
            "quantity": "24 tablets", "days_supply": 3})
        given = await cl.post(f"{BASE}/record/administration", headers=rn, json={
            "kind": "medication", "item": "Artemether-lumefantrine 20/120 mg",
            "dose": "4 tablets", "route": "oral", "notes": "Taken with food"})
        care = await cl.post(f"{BASE}/record/administration", headers=rn, json={
            "kind": "care", "item": "Tepid sponging"})
        wrong = [await cl.post(f"{BASE}/record/diagnosis", headers=rn,
                               json={"condition": "Malaria"}),
                 await cl.post(f"{BASE}/record/dispense", headers=mo, json={
                     "medication": "x", "dose": "x", "quantity": "x"}),
                 await cl.post(f"{BASE}/record/administration", headers=rph,
                               json={"kind": "care", "item": "x"})]
        record = (await cl.get(f"{BASE}/record", headers=rn)).json()
        unified = c.UnifiedView.model_validate(
            (await cl.get(f"{BASE}/unified-view", headers=mo)).json())
    assert [r.status_code for r in (diagnosis, dispense, given, care)] == [201] * 4
    assert [r.status_code for r in wrong] == [403] * 3
    entries = [c.ClinicalEntry.model_validate(e) for e in record]
    by_kind = {e.resource["resourceType"]: e for e in entries}
    assert set(by_kind) == {"Condition", "MedicationDispense", "MedicationAdministration",
                            "Procedure"}
    condition = by_kind["Condition"]
    assert condition.kind == "diagnosis" and condition.recorded_by.role == "medical_officer"
    assert condition.details == ["Confirmed", "From the APDT proposal", "Positive RDT and fever"]
    assert by_kind["MedicationDispense"].details == [
        "4 tablets twice daily", "Quantity 24 tablets", "3 days"]
    assert by_kind["MedicationAdministration"].details == [
        "Medication given", "4 tablets", "oral", "Taken with food"]
    assert by_kind["Procedure"].title == "Tepid sponging"
    assert {i.kind for i in unified.items} >= {"diagnosis", "dispense", "administration"}


async def test_the_record_does_not_change_the_proposals(apdt):  # noqa: F811
    mo = h(tok(apdt, "medical_officer"))
    async with client(apdt) as cl:
        before = (await cl.get(f"{BASE}/recommendations", headers=mo)).json()
        await cl.post(f"{BASE}/record/diagnosis", headers=mo,
                      json={"condition": "Typhoid fever", "status": "provisional"})
        after = (await cl.get(f"{BASE}/recommendations", headers=mo)).json()
    assert [r["recommendation_id"] for r in after] == [r["recommendation_id"] for r in before]


async def _decide(cl, headers, role, run_id, decision):
    run = (await cl.get(f"/v1/t/fac-a/runs/{run_id}", headers=headers)).json()
    body = {"decision_id": f"d-{decision}", "decided_by": {"id": f"{role}.fac-a", "role": role},
            "recommendation_id": run["interrupt"]["payload"]["recommendation_id"],
            "decision": decision, "signature": "stub"}
    r = await cl.post(f"/v1/t/fac-a/runs/{run_id}/resume", headers=headers, json=body)
    assert r.status_code == 200, r.text


async def test_a_verified_prescription_opens_follow_up_work_until_it_is_recorded(
        apdt):  # noqa: F811
    mo, rph, rn = (h(tok(apdt, r)) for r in ("medical_officer", "pharmacist", "nurse"))
    async with client(apdt) as cl:

        async def kinds(role, headers):
            items = (await cl.get(f"/v1/t/fac-a/worklists/{role}", headers=headers)).json()
            return {i["kind"] for i in items["items"]}

        await cl.get(f"{BASE}/recommendations", headers=mo)
        run_id = (await cl.post(f"{BASE}/goals/treatment", headers=mo)).json()["run_id"]
        await _decide(cl, mo, "medical_officer", run_id, "sign")
        signed_only = await kinds("pharmacist", rph)
        run_id = (await cl.post(f"{BASE}/goals/treatment", headers=rph)).json()["run_id"]
        await _decide(cl, rph, "pharmacist", run_id, "verify")
        pharmacist, nurse = await kinds("pharmacist", rph), await kinds("nurse", rn)
        await cl.post(f"{BASE}/record/dispense", headers=rph, json={
            "medication": "Artemether-lumefantrine", "dose": "4 tablets twice daily",
            "quantity": "24 tablets"})
        await cl.post(f"{BASE}/record/administration", headers=rn,
                      json={"kind": "medication", "item": "Artemether-lumefantrine"})
        pharmacist_after, nurse_after = await kinds("pharmacist", rph), await kinds("nurse", rn)
    assert "dispense" not in signed_only
    assert "dispense" in pharmacist and "administration" in nurse
    assert "dispense" not in pharmacist_after and "administration" not in nurse_after


async def test_a_closed_episode_takes_no_entries(apdt):  # noqa: F811
    mo = h(tok(apdt, "medical_officer"))
    async with client(apdt) as cl:
        await cl.post(f"{BASE}/close", headers=mo, json={"outcome": "cured"})
        r = await cl.post(f"{BASE}/record/diagnosis", headers=mo, json={"condition": "Malaria"})
    assert r.status_code == 422
