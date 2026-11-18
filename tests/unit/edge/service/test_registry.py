"""Device registry, provisioning and certificate attestation (design 04, 4.2.2)."""

import datetime as dt
import ssl

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from edge.registry import AttestationError, DeviceCA, DeviceRegistry, RegistryError, fingerprint
from tests.unit.edge.service.support import HDT, START


def csr(device_id):
    key = ec.generate_private_key(ec.SECP256R1())
    request = (x509.CertificateSigningRequestBuilder()
               .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, device_id)]))
               .sign(key, hashes.SHA256()))
    return key, request.public_bytes(serialization.Encoding.PEM)


def pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption())


def server_cert(ca, name="edge.local"):
    key = ec.generate_private_key(ec.SECP256R1())
    now = dt.datetime.now(dt.UTC)
    cert = (x509.CertificateBuilder()
            .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)]))
            .issuer_name(ca.cert.subject).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - dt.timedelta(minutes=1))
            .not_valid_after(now + dt.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName(name)]), critical=False)
            .sign(ca.key, hashes.SHA256()))
    return key, cert


@pytest.fixture
def registry():
    return DeviceRegistry(None, DeviceCA.generate(), clock=lambda: START)


def test_register_persists_and_mirrors_a_thing(tmp_path):
    path = tmp_path / "devices.sqlite"
    ca = DeviceCA.generate()
    reg = DeviceRegistry(path, ca, clock=lambda: START)
    seen = []
    reg.on_register(seen.append)
    record = reg.register("po-1", "pulse_oximeter", HDT, model="PO-80", firmware_version="1.2")
    assert record.topic == f"dev/{HDT}/po-1/pulse_oximeter"
    assert seen == [record]
    thing = reg.things.get(record.thing_id)
    assert thing["attributes"]["hdt_id"] == HDT
    with pytest.raises(FileExistsError):
        reg.register("po-1", "pulse_oximeter", HDT)
    with pytest.raises(ValueError, match="unknown device class"):
        reg.register("x-1", "toaster", HDT)
    reg.close()

    reopened = DeviceRegistry(path, ca, clock=lambda: START)
    assert reopened.get("po-1") == record
    replayed = []
    reopened.on_register(replayed.append)
    assert replayed == [record]
    with pytest.raises(RegistryError):
        reopened.get("nope")


def test_provision_signs_the_csr_and_attestation_checks_the_certificate(registry):
    registry.register("po-1", "pulse_oximeter", HDT)
    key, request = csr("po-1")
    record, cert_pem = registry.provision("po-1", request, firmware_version="2.0")
    cert = x509.load_pem_x509_certificate(cert_pem.encode())
    assert cert.public_key().public_numbers() == key.public_key().public_numbers()
    assert record.cert_fingerprint == fingerprint(cert)
    assert record.provisioned_at == START and record.firmware_version == "2.0"
    assert cert.extensions.get_extension_for_class(
        x509.SubjectAlternativeName).value.get_values_for_type(x509.DNSName) == ["po-1"]

    der = cert.public_bytes(serialization.Encoding.DER)
    attested = registry.attest("po-1", der)
    assert attested.attested_at == START
    identity = registry.things.feature(attested.thing_id, "identity")
    assert identity["attested_at"] == START.isoformat()


def test_attestation_refuses_foreign_stale_and_replaced_certificates(registry):
    registry.register("po-1", "pulse_oximeter", HDT)
    _, request = csr("po-1")
    _, cert_pem = registry.provision("po-1", request)
    der = x509.load_pem_x509_certificate(cert_pem.encode()).public_bytes(
        serialization.Encoding.DER)

    other = DeviceCA.generate("another CA")
    foreign = other.issue("po-1", x509.load_pem_x509_csr(csr("po-1")[1]), now=START)
    with pytest.raises(AttestationError, match="not issued"):
        registry.attest("po-1", foreign.public_bytes(serialization.Encoding.DER))

    replaced = registry.ca.issue("po-1", x509.load_pem_x509_csr(csr("po-1")[1]), now=START)
    with pytest.raises(AttestationError, match="fingerprint"):
        registry.attest("po-1", replaced.public_bytes(serialization.Encoding.DER))

    late = DeviceRegistry(None, registry.ca, clock=lambda: START + dt.timedelta(days=900))
    late.register("po-1", "pulse_oximeter", HDT)
    with pytest.raises(AttestationError, match="validity"):
        late.attest("po-1", der)
    assert registry.get("po-1").attested_at is None


def _handshake(client, server, c_in, c_out, s_in, s_out):
    done = {"client": False, "server": False}
    for _ in range(20):
        for name, obj in (("client", client), ("server", server)):
            if not done[name]:
                try:
                    obj.do_handshake()
                    done[name] = True
                except ssl.SSLWantReadError:
                    pass
        if c_out.pending:
            s_in.write(c_out.read())
        if s_out.pending:
            c_in.write(s_out.read())
        if all(done.values()):
            return
    raise AssertionError("TLS handshake did not finish")


def test_attest_tls_reads_the_client_certificate_of_a_mutual_tls_session(registry, tmp_path):
    registry.register("po-1", "pulse_oximeter", HDT)
    device_key, request = csr("po-1")
    _, cert_pem = registry.provision("po-1", request)
    ca_pem = registry.ca.cert_pem

    edge_key, edge_cert = server_cert(registry.ca)
    (tmp_path / "edge.pem").write_bytes(
        edge_cert.public_bytes(serialization.Encoding.PEM) + pem(edge_key))
    (tmp_path / "dev.pem").write_bytes(cert_pem.encode() + pem(device_key))

    server_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    server_ctx.load_cert_chain(tmp_path / "edge.pem")
    server_ctx.load_verify_locations(cadata=ca_pem)
    server_ctx.verify_mode = ssl.CERT_REQUIRED
    client_ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    client_ctx.load_verify_locations(cadata=ca_pem)
    client_ctx.load_cert_chain(tmp_path / "dev.pem")

    bios = [ssl.MemoryBIO() for _ in range(4)]
    c_in, c_out, s_in, s_out = bios
    client = client_ctx.wrap_bio(c_in, c_out, server_hostname="edge.local")
    server = server_ctx.wrap_bio(s_in, s_out, server_side=True)
    _handshake(client, server, c_in, c_out, s_in, s_out)

    record = registry.attest_tls("po-1", server)
    assert record.attested_at == START
