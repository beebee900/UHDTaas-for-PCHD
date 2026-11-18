"""Polar AccessLink API v3 (www.polar.com/accesslink-api, read 2026-10-10).

- Authorization: https://flow.polar.com/oauth2/authorization (scope `accesslink.read_all`)
- Tokens: POST https://polarremote.com/v2/oauth2/token, HTTP Basic client credentials,
  `grant_type=authorization_code`. The response has `access_token`, `token_type`,
  `expires_in` (about one year) and `x_user_id`; the documentation describes no refresh
  token, so an expired token needs a new authorization.
- Continuous heart rate: GET /v3/users/continuous-heart-rate/{date}
- Body temperature: GET /v3/users/biosensing/bodytemperature; `TM_CORE_TEMPERATURE` maps to
  body temperature and `TM_SKIN_TEMPERATURE` to skin temperature. Times carry no offset and
  are read as UTC.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, timedelta
from typing import Any

from ahdt.devices.vendors.base import (
    OAuthClient,
    OAuthConfig,
    Token,
    VendorError,
    VendorReading,
    loinc,
    utc,
)

API = "https://www.polaraccesslink.com"
AUTHORIZE_URL = "https://flow.polar.com/oauth2/authorization"
TOKEN_URL = "https://polarremote.com/v2/oauth2/token"
TEMPERATURE_CODES = {"TM_CORE_TEMPERATURE": "8310-5", "TM_SKIN_TEMPERATURE": "39106-0"}


def config(client_id: str, client_secret: str, redirect_uri: str) -> OAuthConfig:
    return OAuthConfig(AUTHORIZE_URL, TOKEN_URL, client_id, client_secret, redirect_uri,
                       ("accesslink.read_all",))


def continuous_heart_rate(body: Mapping[str, Any]) -> list[VendorReading]:
    day = body["date"]
    return [VendorReading(loinc("8867-4"), float(s["heart_rate"]), "/min",
                          utc(datetime.fromisoformat(f"{day}T{s['sample_time']}")))
            for s in body.get("heart_rate_samples", [])]


def body_temperature(body: Sequence[Mapping[str, Any]]) -> list[VendorReading]:
    out = []
    for period in body:
        code = TEMPERATURE_CODES.get(period.get("measurement_type", ""))
        if code is None:
            continue
        start = utc(datetime.fromisoformat(period["start_time"]))
        for s in period.get("samples", []):
            when = start + timedelta(milliseconds=int(s["recording_time_delta_milliseconds"]))
            out.append(VendorReading(loinc(code), float(s["temperature_celsius"]), "Cel", when))
    return out


class Polar(OAuthClient):
    async def refresh(self, token: Token) -> Token:
        raise VendorError("Polar AccessLink issues no refresh tokens; authorize again")

    def parse_token(self, body: Mapping[str, Any]) -> Token:
        token = super().parse_token(body)
        token.user_id = str(body["x_user_id"]) if "x_user_id" in body else None
        return token

    async def heart_rate(self, token: Token, day: date) -> list[VendorReading]:
        return continuous_heart_rate(await self.get(
            f"{API}/v3/users/continuous-heart-rate/{day.isoformat()}", token))

    async def temperature(self, token: Token) -> list[VendorReading]:
        return body_temperature(await self.get(f"{API}/v3/users/biosensing/bodytemperature",
                                               token))
