"""Garmin Health API (Garmin Connect Developer Program).

The public pages (developer.garmin.com/gc-developer-program/health-api and the Program FAQ,
read 2026-10-10) state that the API delivers JSON summaries (steps, heart rate, sleep,
stress, pulse ox, respiration, body composition, blood pressure) and that every program API
uses OAuth 2.0. The endpoint URLs and the payload schemas are published only to approved
partners in the Garmin Developer Portal. The OAuth flow therefore takes its endpoints from
configuration, and the payload mapper refuses until a documented schema is available.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from ahdt.devices.vendors.base import OAuthClient, OAuthConfig, VendorError, VendorReading


def config(client_id: str, client_secret: str, redirect_uri: str, *, authorize_url: str,
           token_url: str) -> OAuthConfig:
    return OAuthConfig(authorize_url, token_url, client_id, client_secret, redirect_uri,
                       pkce=True)


def summaries(body: Mapping[str, Any]) -> list[VendorReading]:
    raise VendorError("the Garmin Health API schema is available to approved partners only")


class Garmin(OAuthClient):
    pass
