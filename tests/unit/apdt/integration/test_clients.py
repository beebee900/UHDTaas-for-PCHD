"""OpenMRS FHIR2, OpenHIM and ODK Central clients against mocked HTTP; the XLSForms."""

import json

import httpx
import pytest
from openpyxl import load_workbook

from apdt.integration import odk, openhim, openmrs
from tests.unit.apdt.integration.fixtures import DOCS, HDT

# The example data document of the ODK Central OData docs (DOCS["odk_odata"]), with the
# `__system` fields that the same page lists, on a CHW follow-up form.
ODK_PAGE_1 = {
    "@odata.context": "https://your.odk.server/v1/projects/7/forms/chw_follow_up.svc/"
                      "$metadata#Submissions",
    "value": [{
        "__id": "uuid:85cb9aff-005e-4edd-9739-dc9c1a829c44",
        "__system": {"submissionDate": "2026-10-05T09:12:00.000Z", "submitterId": "5",
                     "updatedAt": None, "reviewState": None, "deletedAt": None},
        "meta": {"instanceID": "uuid:85cb9aff-005e-4edd-9739-dc9c1a829c44"},
        "hdt_id": HDT, "visit_date": "2026-10-05", "feeling": "better",
        "danger_signs": "vomiting bleeding", "temperature_c": 37.2, "referral_needed": "no",
        "notes": ""}],
    "@odata.nextLink": "https://your.odk.server/v1/projects/7/forms/chw_follow_up.svc/"
                       "Submissions?%24top=1&%24skiptoken=abc"}
ODK_PAGE_2 = {"value": [{
    "__id": "uuid:297000fd-8eb2-4232-8863-d25f82521b87", "__system": {},
    "hdt_id": HDT, "visit_date": "2026-10-06", "feeling": "same", "danger_signs": "none",
    "referral_needed": "no"}]}


def test_documentation_sources_are_recorded():
    assert all(u.startswith("https://") for u in DOCS.values())


async def test_openmrs_patient_search_and_observation_paging():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        assert request.headers["authorization"].startswith("Basic ")
        if request.url.path.endswith("/Patient"):
            assert request.url.params["identifier"] == "100GEJ"
            return httpx.Response(200, json={"resourceType": "Bundle", "entry": [{"resource": {
                "resourceType": "Patient", "id": "p-uuid",
                "identifier": [{"value": "100GEJ"}, {"value": HDT}]}}]})
        assert request.url.path.endswith("/Observation")
        if "page" not in request.url.params:
            assert request.url.params["patient"] == "p-uuid"
            return httpx.Response(200, json={"resourceType": "Bundle", "link": [
                {"relation": "next", "url": "http://openmrs.test/openmrs/ws/fhir2/R4/"
                                            "Observation?patient=p-uuid&page=2"}],
                "entry": [{"resource": {"resourceType": "Observation", "id": "o1"}}]})
        return httpx.Response(200, json={"resourceType": "Bundle", "entry": [
            {"resource": {"resourceType": "Observation", "id": "o2"}}]})

    client = openmrs.OpenMrsFhirClient("http://openmrs.test/openmrs/ws/fhir2/R4", "admin",
                                       "test-password", transport=httpx.MockTransport(handler))
    assert await openmrs.patient_index(client)("urn:x", "100GEJ") == HDT
    obs = await client.observations("p-uuid")
    assert [o["id"] for o in obs] == ["o1", "o2"]
    assert seen[0].url.path == "/openmrs/ws/fhir2/R4/Patient"
    await client.aclose()


async def test_openhim_mediator_registration_and_heartbeat():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.raw_path.decode(),
                      json.loads(request.content) if request.content else None))
        if request.url.path.endswith("/heartbeat"):
            return httpx.Response(200, json={"apdtUrl": "http://apdt:8200"})
        return httpx.Response(201)

    him = openhim.OpenHimClient("https://openhim.test:8080", "root@openhim.org",
                                "test-password", transport=httpx.MockTransport(handler))
    mediator = openhim.atra_mediator("apdt", 8200)
    await him.register(mediator)
    config = await him.heartbeat(mediator["urn"], 12.5, want_config=True)
    await him.install_default_channels(mediator["urn"], ["ATRA referral to fac-b"])
    await him.aclose()
    method, path, body = calls[0]
    assert (method, path) == ("POST", "/mediators")
    assert body["urn"] == "urn:openhim-mediator:atra-apdt" and body["endpoints"]
    referral = next(c for c in body["defaultChannelConfig"]
                    if c["name"] == "ATRA referral to fac-b")
    assert referral["urlPattern"] == "^/referral/fac-b$" and referral["allow"]
    assert referral["routes"][0]["path"] == "/v1/t/fac-b/integration/referral"
    assert calls[1][1] == "/mediators/urn%3Aopenhim-mediator%3Aatra-apdt/heartbeat"
    assert calls[1][2] == {"uptime": 12.5, "config": True} and config
    assert calls[2][2] == ["ATRA referral to fac-b"]
    with pytest.raises(ValueError):
        await him.register({**mediator, "endpoints": []})
    reply = openhim.mediator_response(mediator["urn"], "Successful", {"status": 200})
    assert reply["x-mediator-urn"] == mediator["urn"]
    with pytest.raises(ValueError):
        openhim.mediator_response(mediator["urn"], "Done", {})


async def test_odk_pull_logs_in_once_and_follows_next_links():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path == "/v1/sessions":
            assert json.loads(request.content) == {"email": "chw@example.org",
                                                   "password": "test-password"}
            return httpx.Response(200, json={"createdAt": "2026-10-05T03:04:51.695Z",
                                             "expiresAt": "2026-10-06T03:04:51.695Z",
                                             "token": "test-token"})
        assert request.headers["authorization"] == "Bearer test-token"
        assert request.url.path == "/v1/projects/7/forms/chw_follow_up.svc/Submissions"
        if "%24skiptoken" in str(request.url) or "$skiptoken" in str(request.url):
            return httpx.Response(200, json=ODK_PAGE_2)
        assert request.url.params["$filter"] == "__system/submissionDate gt 2026-10-01"
        return httpx.Response(200, json=ODK_PAGE_1)

    client = odk.OdkCentralClient("https://your.odk.server", "chw@example.org",
                                  "test-password", transport=httpx.MockTransport(handler))
    responses = await client.pull(7, "chw_follow_up", since="2026-10-01")
    await client.aclose()
    assert sum(c.url.path == "/v1/sessions" for c in calls) == 1
    first, second = responses
    assert first["subject"]["identifier"]["value"] == HDT
    assert first["authored"].startswith("2026-10-05T09:12:00")
    items = {i["linkId"]: i["answer"] for i in first["item"]}
    assert [a["valueCoding"]["code"] for a in items["danger_signs"]] == ["vomiting", "bleeding"]
    assert items["temperature_c"] == [{"valueDecimal": 37.2}]
    assert "notes" not in items and "hdt_id" not in items
    assert second["questionnaire"] == odk.QUESTIONNAIRE_BASE + "chw_follow_up"


def test_xlsforms_follow_the_form_definitions():
    for form in odk.FORMS:
        wb = load_workbook(odk.FORMS_DIR / f"{form.form_id}.xlsx")
        assert wb.sheetnames == ["survey", "choices", "settings"]
        rows = list(wb["survey"].iter_rows(values_only=True))
        assert rows[0][:3] == ("type", "name", "label::English (en)")
        assert [r[1] for r in rows[1:]] == [q.name for q in form.questions]
        lists = {r[0] for r in list(wb["choices"].iter_rows(values_only=True))[1:]}
        used = {q.type.split(" ")[1] for q in form.questions if " " in q.type}
        assert used == lists
        settings = list(wb["settings"].iter_rows(values_only=True))
        assert settings[1][:3] == (form.title, form.form_id, odk.VERSION)
