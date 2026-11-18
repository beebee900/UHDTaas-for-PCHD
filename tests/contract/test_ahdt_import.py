import io

import pydicom
from pydicom.dataset import FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid
from starlette.testclient import TestClient

from ahdt.app import build_app
from atra.contracts import Role
from atra.personas import BY_KEY

HDT = BY_KEY["ao"].hdt_id


def dicom_bytes(patient_id):
    meta = FileMetaDataset()
    meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.1"
    meta.MediaStorageSOPInstanceUID = generate_uid()
    meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds = pydicom.Dataset()
    ds.file_meta = meta
    ds.PatientID, ds.PatientName, ds.PatientBirthDate = patient_id, "Doe^Jane", "19800101"
    ds.StudyInstanceUID, ds.SeriesInstanceUID = generate_uid(), generate_uid()
    ds.SOPInstanceUID = meta.MediaStorageSOPInstanceUID
    ds.SOPClassUID, ds.Modality = meta.MediaStorageSOPClassUID, "CR"
    buf = io.BytesIO()
    ds.save_as(buf, enforce_file_format=True)
    return buf.getvalue()


def test_import_route(settings, backends):
    app = build_app(settings, backends=backends("ahdt"))
    issuer = app.state.backends.issuer
    svc = {"authorization": f"Bearer {issuer.issue_service('edge-svc')}"}
    lab = {"authorization": "Bearer " + issuer.issue("lab-1", Role.LAB_SCIENTIST,
                                                     tenant_id="fac-a")}
    person = {"authorization": "Bearer " + issuer.issue("p", Role.PERSON, hdt_id=HDT)}
    csv = ("record_id,hdt_id,code_system,code,value,unit,effective_time\n"
           f"c1,{HDT},loinc,8310-5,37.1,Cel,2026-10-01T08:00:00\n"
           f"c2,{HDT},loinc,8310-5,61,Cel,2026-10-01T09:00:00\n")
    with TestClient(app) as client:
        r = client.post("/v1/import?format=csv", content=csv, headers=lab)
        assert r.status_code == 200, r.text
        body = r.json()
        assert (body["accepted"], body["rejected"]) == (1, 1)
        assert body["rejected_records"][0]["record_id"] == "c2"
        assert client.post("/v1/import?format=csv", content=csv,
                           headers=person).status_code == 403
        r = client.post("/v1/import?format=dicom", content=dicom_bytes("LUTH-77"), headers=svc)
        assert r.status_code == 200, r.text
        stored = r.json()
        assert stored["hdt_id"].startswith("hdt-")
        data = app.state.backends.objects
        saved = pydicom.dcmread(io.BytesIO(
            client.portal.call(data.get, stored["key"])))
        assert saved.PatientID == stored["hdt_id"] and "PatientBirthDate" not in saved
        assert client.post("/v1/import?format=vcf", content=b"junk", headers=svc,
                           params={"hdt_id": HDT}).status_code == 422


def test_phkg_export_route(settings, backends):
    app = build_app(settings, backends=backends("ahdt"))
    issuer = app.state.backends.issuer
    mo = {"authorization": "Bearer " + issuer.issue("mo-1", Role.MEDICAL_OFFICER,
                                                    tenant_id="fac-a")}
    other = {"authorization": "Bearer " + issuer.issue(
        "p", Role.PERSON, hdt_id=BY_KEY["gh"].hdt_id)}
    with TestClient(app) as client:
        client.portal.call(app.state.knowledge.phkg.condition, HDT, "cond.malaria_falciparum")
        r = client.get(f"/v1/persons/{HDT}/phkg.ttl", headers=mo)
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/turtle")
        assert "Plasmodium falciparum malaria" in r.text
        assert client.get(f"/v1/persons/{HDT}/phkg.ttl", headers=other).status_code == 403
