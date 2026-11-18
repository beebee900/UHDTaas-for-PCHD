"""Tokens, transport security and per-person envelope encryption (design 07, 7.1).

- `LocalIssuer` signs RS256 tokens with the realm's claims in p0; Keycloak signs them in p2.
- `TokenVerifier` checks signature, audience and expiry against a JWKS, whichever issuer.
- `Keyring` is the p0 stand-in for Vault transit: one AES-256-GCM key per `hdt_id`.
  Deleting the key makes that person's sealed fields unreadable (crypto-shredding).
"""

from __future__ import annotations

import base64
import json
import os
import ssl
import threading
import time
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from jose import JWTError, jwk, jwt
from pydantic import BaseModel, ConfigDict, Field

from atra.contracts import Role

ALGORITHM = "RS256"


class Claims(BaseModel):
    """Token claims of design 03, section 3.13."""

    model_config = ConfigDict(extra="allow")

    sub: str
    role: Role | None = None
    client_id: str | None = None
    tenant_id: str | None = None
    hdt_id: str | None = None
    scope: str = ""
    proxy_for: list[str] = Field(default_factory=list)
    carer_for: list[str] = Field(default_factory=list)
    iss: str
    aud: str | list[str]
    exp: int
    iat: int

    @property
    def scopes(self) -> frozenset[str]:
        return frozenset(self.scope.split())

    @property
    def is_service(self) -> bool:
        """A service client (SMART Backend Services) that acts for a human named in headers."""
        return self.role is None and self.client_id is not None and any(
            s.startswith("system/") for s in self.scopes)

    def policy_view(self) -> dict[str, Any]:
        """The claims an OPA policy sees."""
        return {"sub": self.sub, "role": self.role.value if self.role else None,
                "client_id": self.client_id, "tenant_id": self.tenant_id,
                "hdt_id": self.hdt_id, "proxy_for": self.proxy_for,
                "carer_for": self.carer_for, "scopes": sorted(self.scopes)}


class InvalidToken(PermissionError):
    pass


def _load_or_create_key(path: Path) -> rsa.RSAPrivateKey:
    if path.exists():
        key = serialization.load_pem_private_key(path.read_bytes(), password=None)
        if not isinstance(key, rsa.RSAPrivateKey):
            raise TypeError(f"{path} is not an RSA private key")
        return key
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                                       serialization.PrivateFormat.PKCS8,
                                       serialization.NoEncryption()))
    path.chmod(0o600)
    return key


class LocalIssuer:
    """Local OIDC-style issuer used in profile p0."""

    def __init__(self, issuer: str, audience: str, *, key_path: Path | None = None,
                 ttl_s: int = 3600, kid: str = "atra-local-1") -> None:
        self.issuer, self.audience, self.ttl_s, self.kid = issuer, audience, ttl_s, kid
        if key_path is None:
            self._key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        else:
            self._key = _load_or_create_key(key_path)
        self._pem = self._key.private_bytes(serialization.Encoding.PEM,
                                            serialization.PrivateFormat.PKCS8,
                                            serialization.NoEncryption()).decode()

    def issue(self, sub: str, role: Role | None, *, tenant_id: str | None = None,
              hdt_id: str | None = None, scopes: Iterable[str] = (),
              proxy_for: Iterable[str] = (), carer_for: Iterable[str] = (),
              ttl_s: int | None = None, **extra: Any) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "iss": self.issuer, "aud": self.audience, "sub": sub,
            "iat": now, "exp": now + (ttl_s or self.ttl_s), "scope": " ".join(scopes), **extra}
        if role is not None:
            claims["role"] = role.value
        for name, value in (("tenant_id", tenant_id), ("hdt_id", hdt_id)):
            if value:
                claims[name] = value
        if proxy_for:
            claims["proxy_for"] = list(proxy_for)
        if carer_for:
            claims["carer_for"] = list(carer_for)
        return str(jwt.encode(claims, self._pem, algorithm=ALGORITHM,
                              headers={"kid": self.kid}))

    def issue_service(self, client_id: str, *, scopes: Iterable[str] = ("system/*.rs",),
                      ttl_s: int | None = None) -> str:
        """Client-credentials token of a service client (SMART Backend Services)."""
        return self.issue(f"svc:{client_id}", None, scopes=scopes, ttl_s=ttl_s,
                          client_id=client_id)

    def jwks(self) -> dict[str, Any]:
        public = self._key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        key = jwk.construct(public.decode(), ALGORITHM).to_dict()
        key.update({"kid": self.kid, "use": "sig", "alg": ALGORITHM})
        return {"keys": [key]}


class TokenVerifier:
    """Verifies bearer tokens against a JWKS (local issuer or Keycloak)."""

    def __init__(self, jwks: Mapping[str, Any], *, issuer: str, audience: str,
                 leeway_s: int = 30) -> None:
        self.keys = {k.get("kid"): k for k in jwks.get("keys", [])}
        self.issuer, self.audience, self.leeway_s = issuer, audience, leeway_s

    def verify(self, token: str) -> Claims:
        try:
            header = jwt.get_unverified_header(token)
            key = self.keys.get(header.get("kid")) or next(iter(self.keys.values()), None)
            if key is None:
                raise InvalidToken("no signing key")
            data = jwt.decode(token, key, algorithms=[ALGORITHM], audience=self.audience,
                              issuer=self.issuer, options={"leeway": self.leeway_s})
            return Claims.model_validate(data)
        except (JWTError, ValueError) as exc:
            raise InvalidToken(str(exc)) from exc


def bearer(header_value: str | None) -> str:
    if not header_value or not header_value.lower().startswith("bearer "):
        raise InvalidToken("missing bearer token")
    return header_value.split(" ", 1)[1].strip()


class KeyShredded(LookupError):
    """The person's key was deleted; their sealed data cannot be read."""


class Keyring:
    """Per-person AES-256-GCM keys in a local file, the p0 stand-in for Vault transit.

    `seal` returns a self-describing token `v1:<key version>:<nonce>:<ciphertext>`
    (base64url), so a rotated key still opens older ciphertexts.
    """

    def __init__(self, path: Path | None = None) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._keys: dict[str, dict[str, str]] = {}
        if path is not None and path.exists():
            self._keys = json.loads(path.read_text(encoding="utf-8"))

    def _save(self) -> None:
        if self.path is None:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._keys), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(self.path)

    def ensure_key(self, key_id: str) -> int:
        with self._lock:
            versions = self._keys.setdefault(key_id, {})
            if not versions:
                versions["1"] = _b64(AESGCM.generate_key(bit_length=256))
                self._save()
            return max(int(v) for v in versions)

    def rotate(self, key_id: str) -> int:
        with self._lock:
            versions = self._keys.setdefault(key_id, {})
            new = max((int(v) for v in versions), default=0) + 1
            versions[str(new)] = _b64(AESGCM.generate_key(bit_length=256))
            self._save()
            return new

    def seal(self, key_id: str, plaintext: bytes, *, aad: bytes = b"") -> str:
        version = self.ensure_key(key_id)
        key = _unb64(self._keys[key_id][str(version)])
        nonce = os.urandom(12)
        ct = AESGCM(key).encrypt(nonce, plaintext, aad or key_id.encode())
        return f"v1:{version}:{_b64(nonce)}:{_b64(ct)}"

    def open(self, key_id: str, token: str, *, aad: bytes = b"") -> bytes:
        _, version, nonce, ct = token.split(":", 3)
        versions = self._keys.get(key_id)
        if not versions or version not in versions:
            raise KeyShredded(key_id)
        return AESGCM(_unb64(versions[version])).decrypt(_unb64(nonce), _unb64(ct),
                                                         aad or key_id.encode())

    def shred(self, key_id: str) -> bool:
        """Delete every version of the key. Returns False when there was no key."""
        with self._lock:
            existed = self._keys.pop(key_id, None) is not None
            self._save()
            return existed


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def server_ssl_context(cert: Path, key: Path, ca: Path) -> ssl.SSLContext:
    """mTLS server context: the client must present a certificate from the local CA."""
    ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH, cafile=str(ca))
    ctx.load_cert_chain(str(cert), str(key))
    ctx.verify_mode = ssl.CERT_REQUIRED
    return ctx


def client_ssl_context(cert: Path, key: Path, ca: Path) -> ssl.SSLContext:
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH, cafile=str(ca))
    ctx.load_cert_chain(str(cert), str(key))
    return ctx
