"""Vendor cloud adapters (design 04, 4.1.1): OAuth 2.0 flows and payload mappers for Fitbit,
Garmin, Polar, Withings and Dexcom. Mapped readings become `RawObservation`s for the WP12
pipeline through `VendorReading.raw`."""

from ahdt.devices.vendors.base import OAuthClient, OAuthConfig, Token, VendorError, VendorReading

__all__ = ["OAuthClient", "OAuthConfig", "Token", "VendorError", "VendorReading"]
