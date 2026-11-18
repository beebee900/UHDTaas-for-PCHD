"""The malaria RDT ORU becomes a DiagnosticReport in the episode, on the p0 path and on the
Mirth path (WP20 acceptance 1); critical-result paging; DICOM SR; referral over the HIE."""

import base64
import io
import json

import highdicom as hd
import httpx
import pytest
from pydicom.dataset import Dataset
from pydicom.sr.codedict import codes
from pydicom.uid import generate_uid

from apdt.app import build_app
from apdt.integration import dicom_sr, hie, hl7v2
from apdt.integration.critical import CriticalRules
from apdt.integration.openhim import OpenHimClient
from apdt.records.episodes import PATIENT_SYSTEM, EpisodeRecord
from atra.backends import Backends
from atra.config import ROOT, Settings
from atra.contracts import Code
from atra.kb import KnowledgeBase
from tests.unit.apdt.integration.fixtures import ADT_A01, HDT, POTASSIUM_ORU, RDT_ORU
from tests.unit.apdt.integration.test_hl7v2_mirth import (
    channel_script,
    needs_node,
    run_step,
)


@pytest.fixture
def apdt(tmp_path):
    settings = Settings(var_dir=tmp_path)
    return build_app(settings, backends=Backends(settings, "apdt", ephemeral=True))


def client(app):
    token = app.state.backends.issuer.issue_service("mirth")
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://apdt",
                             headers={"authorization": f"Bearer {token}"})


async def open_episode(app, tenant="fac-a", placer="SR-0001"):
    record = EpisodeRecord(app.state.backends.fhir, tenant)
    ep = await record.open(HDT, reason="Fever for two days")
    await record.add(ep["id"], {
        "resourceType": "ServiceRequest", "status": "active", "intent": "order",
        "identifier": [{"system": hl7v2.PLACER_SYSTEM, "value": placer}],
        "code": {"coding": [{"system": "http://loinc.org", "code": "76772-3"}]}})
    return record, ep["id"]


def assert_rdt_report(reports, observations):
    assert len(reports) == 1
    report = reports[0]
    assert report["code"]["coding"][0]["code"] == "76772-3" and report["status"] == "final"
    assert report["subject"] == {"identifier": {"system": PATIENT_SYSTEM, "value": HDT}}
    ref = report["result"][0]["reference"].split("/")[1]
    obs = next(o for o in observations if o["id"] == ref)
    assert obs["valueCodeableConcept"]["coding"][0]["code"] == "10828004"


async def test_p0_path_files_the_rdt_report_in_the_episode(apdt):
    record, eid = await open_episode(apdt)
    async with client(apdt) as h:
        resp = await h.post("/v1/t/fac-a/integration/hl7v2", content=RDT_ORU,
                            headers={"content-type": "x-application/hl7-v2+er7"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["filed"][0]["episode_id"] == eid
    assert_rdt_report(await record.resources(eid, "DiagnosticReport"),
                      await record.resources(eid, "Observation"))
    audit = apdt.state.audit.query(action="file")
    assert audit[-1].outcome == "ok" and audit[-1].episode_id == eid


@needs_node
async def test_mirth_path_files_the_rdt_report_in_the_episode(apdt):
    record, eid = await open_episode(apdt)
    bundle = run_step(channel_script("atra-hl7v2-to-fhir.xml"), RDT_ORU)
    async with client(apdt) as h:
        resp = await h.post("/v1/t/fac-a/integration/fhir", content=json.dumps(bundle),
                            headers={"content-type": "application/fhir+json"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["episode_id"] == eid
    assert_rdt_report(await record.resources(eid, "DiagnosticReport"),
                      await record.resources(eid, "Observation"))


async def test_resent_result_replaces_the_earlier_version(apdt):
    record, eid = await open_episode(apdt)
    async with client(apdt) as h:
        for text in (RDT_ORU.replace("|F|||2026", "|P|||2026"), RDT_ORU):
            assert (await h.post("/v1/t/fac-a/integration/hl7v2", content=text)).status_code \
                == 200
    obs = await record.resources(eid, "Observation")
    assert len(obs) == 1 and obs[0]["status"] == "final" and obs[0]["meta"]["versionId"] == "2"


async def test_user_tokens_and_unknown_patients_are_refused(apdt):
    await open_episode(apdt)
    user = apdt.state.backends.issuer.issue("lab.fac-a", None, tenant_id="fac-a")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=apdt),
                                 base_url="http://apdt") as h:
        resp = await h.post("/v1/t/fac-a/integration/hl7v2", content=RDT_ORU,
                            headers={"authorization": f"Bearer {user}"})
        assert resp.status_code == 403
    async with client(apdt) as h:
        other = RDT_ORU.replace(f"{HDT}^^^ATRA", "MRN-77^^^FAC-A")
        assert (await h.post("/v1/t/fac-a/integration/hl7v2", content=other)).status_code == 409
    assert apdt.state.audit.query(action="file")[-1].outcome == "error"


async def test_admission_opens_an_episode(apdt):
    async with client(apdt) as h:
        resp = await h.post("/v1/t/fac-b/integration/hl7v2", content=ADT_A01)
    assert resp.status_code == 200, resp.text
    record = EpisodeRecord(apdt.state.backends.fhir, "fac-b")
    [ep] = await record.episodes_of(HDT)
    [enc] = await record.resources(ep["id"], "Encounter")
    assert enc["episodeOfCare"] == [{"reference": f"EpisodeOfCare/{ep['id']}"}]


def test_critical_rules_read_kb_cut_offs():
    rules = CriticalRules(KnowledgeBase(ROOT / "kb"))
    k = Code(system="http://loinc.org", code="2823-3")
    hits = rules.check(k, 7.0, "mmol/L")
    assert hits and hits[0].rule_id == "hyperkalaemia" and hits[0].urgency == "emergency"
    assert hits[0].threshold == 6.5
    assert rules.check(k, 4.1, "mmol/L") == []
    sodium = Code(system="http://loinc.org", code="2951-2")
    assert {h.rule_id for h in rules.check(sodium, 125, "mmol/L", age_years=10)} == {
        "hyponatraemia_child"}
    assert rules.check(sodium, 125, "mmol/L", age_years=40) == []


async def test_critical_potassium_is_paged(apdt):
    await open_episode(apdt)
    raised, paged = [], []

    async def on_alert(event):
        raised.append(event)

    async def sms_page(alert):
        paged.append(alert)

    apdt.state.backends.events.subscribe("alert.raised", on_alert)
    apdt.state.integration.pager.sms_page = sms_page
    async with client(apdt) as h:
        resp = await h.post("/v1/t/fac-a/integration/hl7v2", content=POTASSIUM_ORU)
    assert resp.status_code == 200, resp.text
    assert len(resp.json()["filed"][0]["alerts"]) == 1
    await apdt.state.backends.events.close()
    assert raised and raised[0].payload["severity"] == "emergency"
    assert raised[0].payload["to"] == {"role": "medical_officer",
                                       "id": "medical_officer.fac-a"}
    assert paged and "potassium" in paged[0]["reason"]


def make_sr() -> bytes:
    img = Dataset()
    img.SOPClassUID = "1.2.840.10008.5.1.4.1.1.1.1"
    img.SOPInstanceUID, img.StudyInstanceUID = generate_uid(), generate_uid()
    img.SeriesInstanceUID = generate_uid()
    img.PatientID, img.IssuerOfPatientID = HDT, "ATRA"
    img.PatientName, img.PatientBirthDate, img.PatientSex = "A^O", "", "F"
    img.StudyID, img.AccessionNumber = "1", "ACC-1"
    img.StudyDate, img.StudyTime = "20261001", "100000"
    img.ReferringPhysicianName, img.Modality = "", "DX"
    observer = hd.sr.ObserverContext(
        observer_type=codes.DCM.Person,
        observer_identifying_attributes=hd.sr.PersonObserverIdentifyingAttributes(
            name="Rad^One"))
    group = hd.sr.MeasurementsAndQualitativeEvaluations(
        tracking_identifier=hd.sr.TrackingIdentifier(uid=generate_uid(), identifier="f1"),
        measurements=[hd.sr.Measurement(name=codes.SCT.Diameter, value=12.5,
                                        unit=codes.UCUM.Millimeter)],
        qualitative_evaluations=[hd.sr.QualitativeEvaluation(name=codes.DCM.Finding,
                                                             value=codes.SCT.Mass)])
    report = hd.sr.MeasurementReport(
        observation_context=hd.sr.ObservationContext(observer_person_context=observer),
        procedure_reported=codes.cid100.CTUnspecifiedBodyRegion, imaging_measurements=[group])
    sr = hd.sr.Comprehensive3DSR(
        evidence=[img], content=report[0], series_instance_uid=generate_uid(), series_number=2,
        sop_instance_uid=generate_uid(), instance_number=1, manufacturer="ATRA",
        is_complete=True, is_final=True, is_verified=True, verifying_observer_name="Rad^One",
        verifying_organization="fac-a")
    buf = io.BytesIO()
    sr.save_as(buf)
    return buf.getvalue()


def test_dicom_sr_maps_to_diagnostic_report():
    m = dicom_sr.map_sr(make_sr())
    report = m.resources[-1]
    assert report["status"] == "final" and report["category"][0]["coding"][0]["code"] == "RAD"
    assert report["code"]["coding"][0]["code"] == "25045-6"
    num, coded = m.resources[:2]
    assert num["valueQuantity"] == {"value": 12.5, "unit": "mm",
                                    "system": "http://unitsofmeasure.org", "code": "mm"}
    assert num["code"]["coding"][0]["code"] == "81827009"
    assert coded["valueCodeableConcept"]["coding"][0]["code"] == "4147007"
    assert len(report["result"]) == 2 and m.patient == (PATIENT_SYSTEM, HDT)


async def test_dicom_sr_route_takes_base64_from_mirth(apdt):
    record, eid = await open_episode(apdt)
    async with client(apdt) as h:
        resp = await h.post("/v1/t/fac-a/integration/dicom-sr",
                            content=base64.b64encode(make_sr()))
    assert resp.status_code == 200, resp.text
    [report] = await record.resources(eid, "DiagnosticReport")
    assert report["imagingStudy"][0]["identifier"]["system"] == dicom_sr.DICOM_UID


async def test_referral_travels_through_openhim_to_the_other_facility(apdt):
    record, eid = await open_episode(apdt)
    async with client(apdt) as h:
        await h.post("/v1/t/fac-a/integration/hl7v2", content=RDT_ORU)
    bundle = await hie.referral_bundle(record, eid, to_tenant="fac-b", reason="Severe malaria",
                                       requester="medical_officer.fac-a")
    request = bundle["entry"][0]["resource"]
    assert request["code"]["coding"][0]["code"] == "3457005"
    assert {r["resource"]["resourceType"] for r in bundle["entry"][1:]} == {
        "Observation", "DiagnosticReport"}
    assert all(hie.EPISODE_EXT not in json.dumps(e["resource"]) for e in bundle["entry"])
    token = apdt.state.backends.issuer.issue_service("openhim")
    routed = []

    async def openhim(request: httpx.Request) -> httpx.Response:
        # OpenHIM routes the channel `^/referral/fac-b$` to the fac-b APDT inbox.
        assert request.url.path == "/referral/fac-b"
        assert request.headers["authorization"].startswith("Basic ")
        routed.append(request)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=apdt),
                                     base_url="http://apdt") as h:
            resp = await h.post("/v1/t/fac-b/integration/referral", content=request.content,
                                headers={"authorization": f"Bearer {token}",
                                         "content-type": "application/fhir+json"})
        return httpx.Response(resp.status_code, content=resp.content,
                              headers={"content-type": "application/json"})

    him = OpenHimClient("https://openhim.test:8080", "atra@example.org", "test-password",
                        router_url="https://openhim.test:5000",
                        transport=httpx.MockTransport(openhim))
    result = await hie.HieRouter(him).send("fac-b", bundle)
    await him.aclose()
    assert routed and result["hdt_id"] == HDT
    received = EpisodeRecord(apdt.state.backends.fhir, "fac-b")
    [ep] = await received.episodes_of(HDT)
    assert ep["type"][0]["text"] == "Referral: Severe malaria"
    assert len(await received.resources(ep["id"], "DiagnosticReport")) == 1
    assert len(await received.resources(ep["id"], "ServiceRequest")) == 1
