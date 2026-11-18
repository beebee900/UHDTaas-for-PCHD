"""OAuth 2.0 authorization-code clients and the vendor reading type.

Every vendor follows RFC 6749 section 4.1: the person opens `authorization_url`, the vendor
redirects back with a code, `exchange` trades it for tokens and `refresh` renews them. The
HTTP client is injected, so tests answer with recorded documentation samples and no request
leaves the process. PKCE (RFC 7636) uses the S256 method.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import httpx

from ahdt.ingest.harmonise import RawObservation
from atra.codes import SYSTEMS
from atra.contracts import Code
from atra.ids import new_record_id

FIELD_SYSTEM = "urn:atra:field"


class VendorError(RuntimeError):
    pass


def loinc(code: str) -> Code:
    return Code(system=SYSTEMS["loinc"], code=code)


def twin_field(name: str) -> Code:
    return Code(system=FIELD_SYSTEM, code=name)


def utc(t: datetime) -> datetime:
    """Vendor times without an offset are read as UTC."""
    return t if t.tzinfo else t.replace(tzinfo=UTC)


@dataclass(frozen=True)
class VendorReading:
    code: Code
    value: float
    unit: str
    time: datetime

    def raw(self, *, hdt_id: str, device_id: str, key: str) -> RawObservation:
        """`key` makes repeated fetches of the same vendor record idempotent."""
        return RawObservation(record_id=new_record_id(), code=self.code, value=self.value,
                              unit=self.unit, effective_time=self.time, source="device",
                              hdt_id=hdt_id, device_id=device_id, idempotency_key=key)


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    return verifier, pkce_challenge(verifier)


def pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


@dataclass
class Token:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scope: str | None = None
    user_id: str | None = None
    raw: Mapping[str, Any] = field(default_factory=dict)

    def expired(self, now: datetime) -> bool:
        return self.expires_at is not None and now >= self.expires_at


@dataclass(frozen=True)
class OAuthConfig:
    authorize_url: str
    token_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scopes: tuple[str, ...] = ()
    scope_separator: str = " "
    basic_auth: bool = True
    """Client credentials in an HTTP Basic header (else as form fields)."""
    pkce: bool = False
    token_params: Mapping[str, str] = field(default_factory=dict)
    """Extra form fields every token request carries."""


class OAuthClient:
    def __init__(self, config: OAuthConfig, http: httpx.AsyncClient, *,
                 clock: Any = lambda: datetime.now(UTC)) -> None:
        self.config = config
        self.http = http
        self.clock = clock

    def authorization_url(self, state: str, *, code_challenge: str | None = None,
                          extra: Mapping[str, str] | None = None) -> str:
        c = self.config
        params = {"response_type": "code", "client_id": c.client_id,
                  "redirect_uri": c.redirect_uri, "state": state}
        if c.scopes:
            params["scope"] = c.scope_separator.join(c.scopes)
        if c.pkce:
            if code_challenge is None:
                raise VendorError("this vendor needs a PKCE code challenge")
            params |= {"code_challenge": code_challenge, "code_challenge_method": "S256"}
        params |= dict(extra or {})
        return f"{c.authorize_url}?{urlencode(params)}"

    async def exchange(self, code: str, *, code_verifier: str | None = None) -> Token:
        form = {"grant_type": "authorization_code", "code": code,
                "redirect_uri": self.config.redirect_uri}
        if code_verifier:
            form["code_verifier"] = code_verifier
        return await self._token(form)

    async def refresh(self, token: Token) -> Token:
        if not token.refresh_token:
            raise VendorError("this token has no refresh token")
        return await self._token({"grant_type": "refresh_token",
                                  "refresh_token": token.refresh_token})

    async def _token(self, form: dict[str, str]) -> Token:
        c = self.config
        form = {**c.token_params, **form}
        headers = {"Accept": "application/json"}
        if c.basic_auth:
            pair = base64.b64encode(f"{c.client_id}:{c.client_secret}".encode()).decode()
            headers["Authorization"] = f"Basic {pair}"
        else:
            form |= {"client_id": c.client_id, "client_secret": c.client_secret}
        response = await self.http.post(c.token_url, data=form, headers=headers)
        if response.status_code != 200:
            raise VendorError(f"token endpoint answered {response.status_code}")
        return self.parse_token(response.json())

    def parse_token(self, body: Mapping[str, Any]) -> Token:
        expires = body.get("expires_in")
        return Token(str(body["access_token"]), body.get("refresh_token"),
                     self.clock() + timedelta(seconds=float(expires)) if expires else None,
                     body.get("scope"), _str(body.get("user_id")), body)

    async def get(self, url: str, token: Token, **params: Any) -> Any:
        response = await self.http.get(url, params=params or None,
                                       headers={"Authorization": f"Bearer {token.access_token}",
                                                "Accept": "application/json"})
        if response.status_code != 200:
            raise VendorError(f"{url} answered {response.status_code}")
        return response.json()


def _str(v: Any) -> str | None:
    return None if v is None else str(v)
