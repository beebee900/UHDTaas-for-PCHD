"""Device registry, provisioning and attestation (design 04, 4.2.2).

A device record holds the device id, class, owner `hdt_id`, certificate fingerprint and
firmware version. Records live in the edge's SQLite file, so they survive a restart, and each
one is mirrored as a Thing in a Dyon `ThingRegistry` (`atra.device:<device_id>`).

Provisioning signs the device's certificate signing request with the local CA (design 07,
7.1.1), so the private key never leaves the device. Attestation checks a certificate the device
presents on TLS: issued by the CA, inside its validity period, and with the fingerprint the
registry holds. It records `attested_at`.
"""

from __future__ import annotations

import datetime as dt
import sqlite3
import ssl
import threading
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, get_args

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID
from dyon.services.ditto.memory import ThingRegistry

DeviceClass = Literal[
    "smartwatch", "ecg_patch", "bp_cuff", "glucometer", "cgm", "pulse_oximeter", "spirometer",
    "smart_scale", "thermometer", "insulin_pump", "cpap", "rehab_robot", "lab_analyser",
    "ecg_machine", "imaging", "genomics", "imu", "pressure_insoles", "phone", "self_report",
    "environmental", "lighting", "ventilation", "records"]
DEVICE_CLASSES: frozenset[str] = frozenset(get_args(DeviceClass))
THING_NAMESPACE = "atra.device"
DEVICE_CERT_DAYS = 825


class RegistryError(LookupError):
    pass


class AttestationError(PermissionError):
    pass


def fingerprint(cert: x509.Certificate) -> str:
    """SHA-256 of the DER certificate, lower-case hex."""
    return cert.fingerprint(hashes.SHA256()).hex()


def _name(cn: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.ORGANIZATION_NAME, "ATRA local"),
                      x509.NameAttribute(NameOID.COMMON_NAME, cn)])


class DeviceCA:
    """The local CA that issues device certificates."""

    def __init__(self, key: ec.EllipticCurvePrivateKey, cert: x509.Certificate) -> None:
        self.key = key
        self.cert = cert

    @classmethod
    def from_dir(cls, directory: Path) -> DeviceCA:
        """The CA written by `make pki` (`ca.key`, `ca.crt`)."""
        key = serialization.load_pem_private_key((directory / "ca.key").read_bytes(), None)
        if not isinstance(key, ec.EllipticCurvePrivateKey):
            raise ValueError("the CA key is not an EC key")
        return cls(key, x509.load_pem_x509_certificate((directory / "ca.crt").read_bytes()))

    @classmethod
    def generate(cls, name: str = "ATRA edge CA") -> DeviceCA:
        """An in-memory CA, for p0 runs without `make pki` and for tests."""
        key = ec.generate_private_key(ec.SECP256R1())
        now = dt.datetime.now(dt.UTC)
        cert = (x509.CertificateBuilder().subject_name(_name(name)).issuer_name(_name(name))
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now).not_valid_after(now + dt.timedelta(days=3650))
                .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
                .sign(key, hashes.SHA256()))
        return cls(key, cert)

    @property
    def cert_pem(self) -> str:
        return self.cert.public_bytes(serialization.Encoding.PEM).decode()

    def issue(self, device_id: str, csr: x509.CertificateSigningRequest, *,
              now: dt.datetime | None = None) -> x509.Certificate:
        if not csr.is_signature_valid:
            raise ValueError("the CSR signature does not verify")
        now = now or dt.datetime.now(dt.UTC)
        return (x509.CertificateBuilder().subject_name(_name(device_id))
                .issuer_name(self.cert.subject).public_key(csr.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(now).not_valid_after(now + dt.timedelta(days=DEVICE_CERT_DAYS))
                .add_extension(x509.SubjectAlternativeName([x509.DNSName(device_id)]),
                               critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
                               critical=False)
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .sign(self.key, hashes.SHA256()))


@dataclass(frozen=True)
class DeviceRecord:
    device_id: str
    device_class: str
    hdt_id: str
    registered_at: dt.datetime
    model: str | None = None
    firmware_version: str | None = None
    cert_fingerprint: str | None = None
    provisioned_at: dt.datetime | None = None
    attested_at: dt.datetime | None = None

    @property
    def topic(self) -> str:
        return f"dev/{self.hdt_id}/{self.device_id}/{self.device_class}"

    @property
    def thing_id(self) -> str:
        return f"{THING_NAMESPACE}:{self.device_id}"


_COLUMNS = ("device_id", "device_class", "hdt_id", "registered_at", "model", "firmware_version",
            "cert_fingerprint", "provisioned_at", "attested_at")
_SCHEMA = """CREATE TABLE IF NOT EXISTS devices (
    device_id TEXT PRIMARY KEY, device_class TEXT NOT NULL, hdt_id TEXT NOT NULL,
    registered_at TEXT NOT NULL, model TEXT, firmware_version TEXT, cert_fingerprint TEXT,
    provisioned_at TEXT, attested_at TEXT)"""
_TIMES = ("registered_at", "provisioned_at", "attested_at")


def _row(record: DeviceRecord) -> tuple[str | None, ...]:
    values = []
    for c in _COLUMNS:
        v = getattr(record, c)
        values.append(v.isoformat() if isinstance(v, dt.datetime) else v)
    return tuple(values)


def _record(row: sqlite3.Row) -> DeviceRecord:
    o = {c: row[c] for c in _COLUMNS}
    for c in _TIMES:
        o[c] = dt.datetime.fromisoformat(o[c]) if o[c] else None
    return DeviceRecord(**o)


Listener = Callable[[DeviceRecord], None]


class DeviceRegistry:
    """Device records in SQLite (`path=None` keeps them in memory), mirrored into Things."""

    def __init__(self, path: Path | None, ca: DeviceCA, *, things: ThingRegistry | None = None,
                 clock: Callable[[], dt.datetime] = lambda: dt.datetime.now(dt.UTC)) -> None:
        self.ca = ca
        self.things = things or ThingRegistry()
        self.clock = clock
        self._lock = threading.Lock()
        self._db = sqlite3.connect(str(path) if path else ":memory:", check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute(_SCHEMA)
        self._db.commit()
        self._listeners: list[Listener] = []
        for record in self.all():
            self._mirror(record)

    def on_register(self, listener: Listener) -> None:
        """Called for every record already held and for every new one."""
        self._listeners.append(listener)
        for record in self.all():
            listener(record)

    def _mirror(self, r: DeviceRecord) -> None:
        self.things.create(r.thing_id, {
            "attributes": {"device_class": r.device_class, "hdt_id": r.hdt_id,
                           "model": r.model, "firmware_version": r.firmware_version},
            "features": {}})
        self.things.update_feature(r.thing_id, "identity", {
            "cert_fingerprint": r.cert_fingerprint,
            "provisioned_at": r.provisioned_at.isoformat() if r.provisioned_at else None,
            "attested_at": r.attested_at.isoformat() if r.attested_at else None})

    def _save(self, record: DeviceRecord) -> DeviceRecord:
        marks = ", ".join("?" * len(_COLUMNS))
        self._db.execute(f"INSERT OR REPLACE INTO devices ({', '.join(_COLUMNS)}) "
                         f"VALUES ({marks})", _row(record))
        self._db.commit()
        self._mirror(record)
        return record

    def get(self, device_id: str) -> DeviceRecord:
        with self._lock:
            row = self._db.execute("SELECT * FROM devices WHERE device_id = ?",
                                   (device_id,)).fetchone()
        if row is None:
            raise RegistryError(f"no device {device_id}")
        return _record(row)

    def all(self) -> list[DeviceRecord]:
        with self._lock:
            rows = self._db.execute("SELECT * FROM devices ORDER BY device_id").fetchall()
        return [_record(r) for r in rows]

    def register(self, device_id: str, device_class: str, hdt_id: str, *,
                 model: str | None = None,
                 firmware_version: str | None = None) -> DeviceRecord:
        if device_class not in DEVICE_CLASSES:
            raise ValueError(f"unknown device class {device_class}")
        with self._lock:
            exists = self._db.execute("SELECT 1 FROM devices WHERE device_id = ?",
                                      (device_id,)).fetchone()
            if exists:
                raise FileExistsError(f"device {device_id} exists")
            record = self._save(DeviceRecord(device_id, device_class, hdt_id, self.clock(),
                                             model, firmware_version))
        for listener in self._listeners:
            listener(record)
        return record

    def provision(self, device_id: str, csr_pem: bytes, *,
                  firmware_version: str | None = None) -> tuple[DeviceRecord, str]:
        """Sign the device's CSR; returns the record and the certificate PEM."""
        record = self.get(device_id)
        csr = x509.load_pem_x509_csr(csr_pem)
        now = self.clock()
        cert = self.ca.issue(device_id, csr, now=now)
        with self._lock:
            record = self._save(replace(
                record, cert_fingerprint=fingerprint(cert), provisioned_at=now,
                firmware_version=firmware_version or record.firmware_version))
        return record, cert.public_bytes(serialization.Encoding.PEM).decode()

    def attest(self, device_id: str, cert_der: bytes) -> DeviceRecord:
        record = self.get(device_id)
        cert = x509.load_der_x509_certificate(cert_der)
        now = self.clock()
        try:
            cert.verify_directly_issued_by(self.ca.cert)
        except (InvalidSignature, ValueError, TypeError) as exc:
            raise AttestationError(f"{device_id}: certificate not issued by the edge CA") from exc
        if not cert.not_valid_before_utc <= now <= cert.not_valid_after_utc:
            raise AttestationError(f"{device_id}: certificate outside its validity period")
        if record.cert_fingerprint is None or fingerprint(cert) != record.cert_fingerprint:
            raise AttestationError(f"{device_id}: certificate fingerprint does not match")
        with self._lock:
            return self._save(replace(record, attested_at=now))

    def attest_tls(self, device_id: str, connection: ssl.SSLObject | ssl.SSLSocket
                   ) -> DeviceRecord:
        """Attest the client certificate of an accepted mutual-TLS connection."""
        der = connection.getpeercert(binary_form=True)
        if der is None:
            raise AttestationError(f"{device_id}: no client certificate on the connection")
        return self.attest(device_id, der)

    def close(self) -> None:
        self._db.close()
