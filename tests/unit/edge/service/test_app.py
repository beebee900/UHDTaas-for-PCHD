"""Edge service endpoints (design 03 edge OpenAPI; design 04, 4.2.2)."""

from datetime import timedelta

from cryptography import x509
from cryptography.hazmat.primitives import serialization
from starlette.testclient import TestClient

from atra.contracts import Role
from edge.app import build_app
from edge.outbox import LinkDown
from tests.unit.edge.service.support import HDT, START, oximeter_frame
from tests.unit.edge.service.test_registry import csr


def client_of(settings, backends, edge_settings):
    app = build_app(settings, backends=backends("edge"), edge=edge_settings, step_s=None)
    issuer = app.state.backends.issuer
    nurse = {"authorization": "Bearer " + issuer.issue("n-1", Role.NURSE, tenant_id="fac-a")}
    pharmacist = {"authorization": "Bearer " + issuer.issue("ph-1", Role.PHARMACIST,
                                                            tenant_id="fac-a")}
    return app, nurse, pharmacist


def test_device_registration_and_provisioning(settings, backends, edge_settings):
    app, nurse, pharmacist = client_of(settings, backends, edge_settings)
    body = {"device_id": "po-1", "device_class": "pulse_oximeter", "hdt_id": HDT,
            "model": "PO-80"}
    with TestClient(app) as c:
        assert c.post("/v1/devices", json=body).status_code == 401
        assert c.post("/v1/devices", json=body, headers=pharmacist).status_code == 403
        created = c.post("/v1/devices", json=body, headers=nurse)
        assert created.status_code == 201
        assert created.json()["topic"] == f"dev/{HDT}/po-1/pulse_oximeter"
        assert not created.json()["provisioned"]
        assert c.post("/v1/devices", json=body, headers=nurse).status_code == 409
        bad = {**body, "device_id": "po-2", "device_class": "toaster"}
        assert c.post("/v1/devices", json=bad, headers=nurse).status_code == 422
        assert [d["device_id"] for d in c.get("/v1/devices", headers=nurse).json()] == ["po-1"]

        key, request = csr("po-1")
        url = "/v1/devices/po-1/provision"
        bad_csr = c.post(url, json={"csr_pem": "not a csr"}, headers=nurse)
        assert bad_csr.status_code == 422
        missing = c.post("/v1/devices/po-9/provision", json={"csr_pem": request.decode()},
                         headers=nurse)
        assert missing.status_code == 404
        done = c.post(url, json={"csr_pem": request.decode(), "firmware_version": "1.4.0"},
                      headers=nurse)
    assert done.status_code == 200
    out = done.json()
    cert = x509.load_pem_x509_certificate(out["certificate_pem"].encode())
    ca = x509.load_pem_x509_certificate(out["ca_pem"].encode())
    cert.verify_directly_issued_by(ca)
    assert cert.public_key().public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo) == \
        key.public_key().public_bytes(serialization.Encoding.DER,
                                      serialization.PublicFormat.SubjectPublicKeyInfo)
    assert out["device"]["provisioned"] and out["device"]["firmware_version"] == "1.4.0"
    assert out["device"]["cert_fingerprint"] == cert.fingerprint(
        cert.signature_hash_algorithm).hex()


class Down:
    async def ingest(self, observations):
        raise LinkDown("AHDT unreachable")


async def test_outbox_link_alerts_and_summary(settings, backends, edge_settings):
    app, nurse, _ = client_of(settings, backends, edge_settings)
    rt = app.state.edge
    rt.forwarder.ingestor = Down()
    with TestClient(app) as c:
        assert c.post("/v1/devices", json={"device_id": "po-1",
                                           "device_class": "pulse_oximeter",
                                           "hdt_id": HDT}, headers=nurse).status_code == 201
        for i in range(12):
            oximeter_frame(rt.transports.mqtt, "po-1", START + timedelta(seconds=10 * i),
                           96 - i % 3, 70, packet_id=i + 1)
        rt.clock = lambda: START + timedelta(minutes=5)
        c.portal.call(rt.step)

        status = c.get("/v1/outbox").json()
        assert status["pending"] == 24 and status["link"] == "down"
        assert status["profile"] == "wifi"
        assert c.put("/v1/link", json={"profile": "2g"}).status_code == 401
        changed = c.put("/v1/link", json={"profile": "offline"}, headers=nurse).json()
        assert changed["profile"] == "offline" and changed["pending"] == 24
        assert c.put("/v1/link", json={"profile": "5g"}, headers=nurse).status_code == 422

        assert c.get("/v1/alerts", headers=nurse).json() == []
        summary = c.get(f"/v1/persons/{HDT}/summary", params={"day": START.date().isoformat()},
                        headers=nurse)
        assert c.get("/v1/persons/nobody/summary", headers=nurse).status_code == 422
    assert summary.status_code == 200
    text = summary.json()["text"]
    assert "spo2: mean 95 %, lowest 94, highest 96, 12 readings." in text
    assert "heart_rate: mean 70 /min" in text
