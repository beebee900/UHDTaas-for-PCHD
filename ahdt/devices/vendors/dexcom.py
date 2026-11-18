"""Dexcom API v3 (developer.dexcom.com, Authentication and Endpoint Overview, read 2026-10-10).

- Authorization: GET {base}/v3/oauth2/login with `client_id`, `redirect_uri`,
  `response_type=code`, `scope=offline_access` and `state`
- Tokens: POST {base}/v3/oauth2/token, form fields `client_id`, `client_secret`, `code`,
  `grant_type`, `redirect_uri`; each refresh token is single-use, so the new one replaces it
- EGVs: GET {base}/v3/users/self/egvs with `startDate` and `endDate` (window at most 30 days).
  Values are mg/dL; 39 and 401 stand for "below 40" and "above 400" and are not
  measurements, so they are left out. Receiver times have no UTC offset and are read as UTC.

Base URLs: sandbox https://sandbox-api.dexcom.com, US https://api.dexcom.com, outside the US
https://api.dexcom.eu, Japan https://api.dexcom.jp.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any

from ahdt.devices.vendors.base import OAuthClient, OAuthConfig, Token, VendorReading, loinc, utc
from atra import units

SANDBOX = "https://sandbox-api.dexcom.com"
GLUCOSE = "15074-8"
SENTINELS = (39, 401)


def config(client_id: str, client_secret: str, redirect_uri: str, *,
           base: str = SANDBOX) -> OAuthConfig:
    return OAuthConfig(f"{base}/v3/oauth2/login", f"{base}/v3/oauth2/token", client_id,
                       client_secret, redirect_uri, ("offline_access",), basic_auth=False)


def egvs(body: Mapping[str, Any]) -> list[VendorReading]:
    """Glucose as the twin field's amount concentration (mmol/L)."""
    out = []
    for r in body.get("records", []):
        value = r.get("value")
        if value is None or value in SENTINELS or r.get("status"):
            continue
        mmol = units.convert(float(value), str(r["unit"]), "mmol/L", substance="glucose")
        out.append(VendorReading(loinc(GLUCOSE), mmol, "mmol/L",
                                 utc(datetime.fromisoformat(r["systemTime"]))))
    return out


class Dexcom(OAuthClient):
    def __init__(self, cfg: OAuthConfig, http: Any, *, base: str = SANDBOX, **kw: Any) -> None:
        super().__init__(cfg, http, **kw)
        self.base = base

    async def glucose(self, token: Token, start: datetime, end: datetime
                      ) -> list[VendorReading]:
        fmt = "%Y-%m-%dT%H:%M:%S"
        return egvs(await self.get(f"{self.base}/v3/users/self/egvs", token,
                                   startDate=start.strftime(fmt), endDate=end.strftime(fmt)))
