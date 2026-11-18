"""Withings Public API (developer.withings.com/api-reference, read 2026-10-10).

- Authorization: https://account.withings.com/oauth2_user/authorize2 (scopes comma-separated)
- Tokens: POST https://wbsapi.withings.net/v2/oauth2 with `action=requesttoken`, client id
  and secret as form fields; the answer is `{status, body: {userid, access_token,
  refresh_token, expires_in, scope, csrf_token, token_type}}` and status 0 means success
- Measures: POST https://wbsapi.withings.net/measure `action=getmeas`; each measure's real
  value is `value * 10^unit` in SI units, `date` is a UNIX timestamp, and `category` 1 is a
  real measure (2 is a user objective)
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from ahdt.devices.vendors.base import (
    OAuthClient,
    OAuthConfig,
    Token,
    VendorError,
    VendorReading,
    loinc,
)

AUTHORIZE_URL = "https://account.withings.com/oauth2_user/authorize2"
TOKEN_URL = "https://wbsapi.withings.net/v2/oauth2"
MEASURE_URL = "https://wbsapi.withings.net/measure"
REAL_MEASURE = 1
MEASURE_TYPES: Mapping[int, tuple[str, str]] = {
    1: ("29463-7", "kg"), 4: ("8302-2", "m"), 9: ("8462-4", "mm[Hg]"),
    10: ("8480-6", "mm[Hg]"), 11: ("8867-4", "/min"), 54: ("59408-5", "%"),
    71: ("8310-5", "Cel"), 73: ("39106-0", "Cel"),
}
"""meastype -> (LOINC, UCUM unit of the documented SI value)."""


def config(client_id: str, client_secret: str, redirect_uri: str) -> OAuthConfig:
    return OAuthConfig(AUTHORIZE_URL, TOKEN_URL, client_id, client_secret, redirect_uri,
                       ("user.info", "user.metrics", "user.activity"), scope_separator=",",
                       basic_auth=False, token_params={"action": "requesttoken"})


def _ok(body: Mapping[str, Any]) -> Mapping[str, Any]:
    if body.get("status") != 0:
        raise VendorError(f"Withings answered status {body.get('status')}")
    inner: Mapping[str, Any] = body["body"]
    return inner


def measures(body: Mapping[str, Any]) -> list[VendorReading]:
    out = []
    for group in _ok(body).get("measuregrps", []):
        if group.get("category", REAL_MEASURE) == 2:
            continue
        when = datetime.fromtimestamp(int(group["date"]), UTC)
        for m in group.get("measures", []):
            mapped = MEASURE_TYPES.get(int(m["type"]))
            if mapped:
                value = int(m["value"]) * 10.0 ** int(m["unit"])
                out.append(VendorReading(loinc(mapped[0]), value, mapped[1], when))
    return out


class Withings(OAuthClient):
    def parse_token(self, body: Mapping[str, Any]) -> Token:
        inner = _ok(body)
        token = super().parse_token(inner)
        token.user_id = str(inner["userid"]) if "userid" in inner else None
        return token

    async def measures(self, token: Token, start: datetime, end: datetime
                       ) -> list[VendorReading]:
        response = await self.http.post(MEASURE_URL, data={
            "action": "getmeas", "meastypes": ",".join(str(t) for t in MEASURE_TYPES),
            "category": str(REAL_MEASURE), "startdate": str(int(start.timestamp())),
            "enddate": str(int(end.timestamp()))},
            headers={"Authorization": f"Bearer {token.access_token}"})
        if response.status_code != 200:
            raise VendorError(f"getmeas answered {response.status_code}")
        return measures(response.json())
