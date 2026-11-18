"""Fitbit Web API (dev.fitbit.com/build/reference/web-api, read 2026-10-10).

- Authorization: https://www.fitbit.com/oauth2/authorize, authorization code with PKCE (S256)
- Tokens: POST https://api.fitbit.com/oauth2/token, client id and secret as HTTP Basic,
  `grant_type=authorization_code` with `code_verifier`, or `grant_type=refresh_token`
- Heart rate intraday: GET /1/user/-/activities/heart/date/{date}/1d/1min.json, with
  `timezone=UTC` so dataset times are UTC
- SpO2 summary: GET /1/user/-/spo2/date/{date}.json; the daily average maps to SpO2
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import Any

from ahdt.devices.vendors.base import OAuthClient, OAuthConfig, Token, VendorReading, loinc, utc

API = "https://api.fitbit.com"
AUTHORIZE_URL = "https://www.fitbit.com/oauth2/authorize"
TOKEN_URL = "https://api.fitbit.com/oauth2/token"
SCOPES = ("heartrate", "oxygen_saturation")
"""The scopes the two endpoint pages name."""


def config(client_id: str, client_secret: str, redirect_uri: str) -> OAuthConfig:
    return OAuthConfig(AUTHORIZE_URL, TOKEN_URL, client_id, client_secret, redirect_uri,
                       SCOPES, pkce=True)


def heart_intraday(body: Mapping[str, Any]) -> list[VendorReading]:
    day = body["activities-heart"][0]["dateTime"]
    return [VendorReading(loinc("8867-4"), float(p["value"]), "/min",
                          utc(datetime.fromisoformat(f"{day}T{p['time']}")))
            for p in body.get("activities-heart-intraday", {}).get("dataset", [])]


def spo2_summary(body: Mapping[str, Any]) -> list[VendorReading]:
    value = body.get("value") or {}
    if "avg" not in value:
        return []
    return [VendorReading(loinc("59408-5"), float(value["avg"]), "%",
                          utc(datetime.fromisoformat(body["dateTime"])))]


class Fitbit(OAuthClient):
    async def heart_rate(self, token: Token, day: date) -> list[VendorReading]:
        url = f"{API}/1/user/-/activities/heart/date/{day.isoformat()}/1d/1min.json"
        return heart_intraday(await self.get(url, token, timezone="UTC"))

    async def spo2(self, token: Token, day: date) -> list[VendorReading]:
        return spo2_summary(await self.get(f"{API}/1/user/-/spo2/date/{day.isoformat()}.json",
                                           token))
