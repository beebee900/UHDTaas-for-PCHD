"""Bandwidth adaptation by link profile (design 04, 4.2.2).

- `wifi`, `4g`: every pre-processed reading goes to the outbox as it arrives, waveforms
  included; batches of 500, uncompressed.
- `2g`: no waveforms; each scalar stream becomes one reading per closed window (a lone
  reading as it is, more than one as their mean); batches of 100, gzip on the gRPC stream.
- `offline`: the outbox fills as on `wifi`, so nothing is lost when the link returns; nothing
  is sent, and critical alerts go by SMS.

The outbox stores every payload zstd-compressed whatever the profile. gRPC Python offers only
gzip and deflate as stream compression, so the `2g` wire uses gzip.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import grpc

from edge.config import LinkProfile
from edge.preprocess import Preprocessed, WindowAccumulator


@dataclass(frozen=True)
class LinkPolicy:
    profile: LinkProfile
    waveforms: bool
    windowed: bool
    deliver: bool
    sms_alerts: bool
    batch_size: int
    compression: grpc.Compression


POLICIES: dict[str, LinkPolicy] = {
    "wifi": LinkPolicy("wifi", True, False, True, False, 500, grpc.Compression.NoCompression),
    "4g": LinkPolicy("4g", True, False, True, False, 500, grpc.Compression.NoCompression),
    "2g": LinkPolicy("2g", False, True, True, False, 100, grpc.Compression.Gzip),
    "offline": LinkPolicy("offline", True, False, False, True, 500,
                          grpc.Compression.NoCompression),
}


def policy(profile: str) -> LinkPolicy:
    try:
        return POLICIES[profile]
    except KeyError:
        raise ValueError(f"unknown link profile {profile}") from None


def _waveform(p: Mapping[str, Any]) -> bool:
    return isinstance(p["value"], Mapping)


def _scalar(p: Mapping[str, Any]) -> bool:
    v = p["value"]
    return isinstance(v, int | float) and not isinstance(v, bool)


class Shaper:
    """Chooses what each pre-processed batch puts in the outbox under the current link.

    On `2g` the scalar readings wait in windows of their own; leaving `2g` closes those
    windows at once, so no reading is held back or sent twice across a profile change."""

    def __init__(self, profile: str, *, window_s: float = 60.0) -> None:
        self.link = policy(profile)
        self._deferred = WindowAccumulator(window_s)

    def set_link(self, profile: str) -> list[dict[str, Any]]:
        """Switch profile; returns the deferred readings that are due now."""
        self.link = policy(profile)
        if self.link.windowed:
            return []
        return [w.payload() for w in self._deferred.close()]

    def select(self, batch: Preprocessed, now: datetime | None) -> list[dict[str, Any]]:
        if not self.link.windowed:
            return [p for p in batch.payloads if self.link.waveforms or not _waveform(p)]
        self._deferred.add(p for p in batch.payloads if _scalar(p))
        out = [p for p in batch.payloads if not _waveform(p) and not _scalar(p)]
        return out + [w.payload() for w in self._deferred.close(now)]

    def flush(self) -> list[dict[str, Any]]:
        """Every deferred reading, at shutdown."""
        return [w.payload() for w in self._deferred.close()]
