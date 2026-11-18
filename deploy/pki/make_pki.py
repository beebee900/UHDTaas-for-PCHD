"""Local certificate authority for mTLS between services and for devices (design 07, 7.1.1).

    python deploy/pki/make_pki.py                     CA plus one certificate per service
    python deploy/pki/make_pki.py --device bp-001     plus a device certificate

Output goes to deploy/pki/out/ (local only). Existing keys are kept; certificates are
reissued when they are missing.
"""

from __future__ import annotations

import argparse
import datetime as dt
import ipaddress
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

OUT = Path(__file__).resolve().parent / "out"
SERVICES = ("edge", "ahdt", "population", "apdt", "channels", "workers", "opa", "kong",
            "mosquitto", "kafka")
VALID_DAYS = 825


def _key(path: Path) -> ec.EllipticCurvePrivateKey:
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        assert isinstance(key, ec.EllipticCurvePrivateKey)
        return key
    key = ec.generate_private_key(ec.SECP256R1())
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)
    return key


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ATRA local"),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])


def ca() -> tuple[ec.EllipticCurvePrivateKey, x509.Certificate]:
    key = _key(OUT / "ca.key")
    cert_path = OUT / "ca.crt"
    if cert_path.exists():
        return key, x509.load_pem_x509_certificate(cert_path.read_bytes())
    now = dt.datetime.now(dt.UTC)
    cert = (x509.CertificateBuilder().subject_name(_name("ATRA local CA"))
            .issuer_name(_name("ATRA local CA")).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now)
            .not_valid_after(now + dt.timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, key_cert_sign=True, crl_sign=True,
                                         content_commitment=False, key_encipherment=False,
                                         data_encipherment=False, key_agreement=False,
                                         encipher_only=False, decipher_only=False), critical=True)
            .sign(key, hashes.SHA256()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return key, cert


def leaf(name: str, ca_key: ec.EllipticCurvePrivateKey, ca_cert: x509.Certificate, *,
         device: bool = False) -> Path:
    stem = f"device-{name}" if device else name
    key = _key(OUT / f"{stem}.key")
    cert_path = OUT / f"{stem}.crt"
    if cert_path.exists():
        return cert_path
    now = dt.datetime.now(dt.UTC)
    sans: list[x509.GeneralName] = [x509.DNSName(name)]
    usages = [ExtendedKeyUsageOID.CLIENT_AUTH]
    if not device:
        sans += [x509.DNSName("localhost"), x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
        usages.append(ExtendedKeyUsageOID.SERVER_AUTH)
    cert = (x509.CertificateBuilder().subject_name(_name(name)).issuer_name(ca_cert.subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now).not_valid_after(now + dt.timedelta(days=VALID_DAYS))
            .add_extension(x509.SubjectAlternativeName(sans), critical=False)
            .add_extension(x509.ExtendedKeyUsage(usages), critical=False)
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(ca_key, hashes.SHA256()))
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--device", action="append", default=[], help="device id")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    ca_key, ca_cert = ca()
    for svc in SERVICES:
        leaf(svc, ca_key, ca_cert)
    for device in args.device:
        leaf(device, ca_key, ca_cert, device=True)
    print(f"certificates in {OUT}")


if __name__ == "__main__":
    main()
