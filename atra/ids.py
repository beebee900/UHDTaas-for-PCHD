"""Identifier formats shared by every service (design 02, section 2.8)."""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
import time
import uuid

HDT_ID_RE = re.compile(r"^hdt-[0-9a-f]{12}$")
EPISODE_ID_RE = re.compile(r"^ep-\d{4}-\d{6}$")
TENANT_IDS = frozenset({"fac-a", "fac-b"})
OUTPUT_ID_RE = re.compile(r"^out-[0-9a-f-]{36}$")
FORK_ID_RE = re.compile(r"^fork-[0-9a-f-]{36}$")

_v7_lock = threading.Lock()
_v7_last = (0, 0)


def uuid7() -> uuid.UUID:
    """RFC 9562 UUIDv7: 48-bit Unix milliseconds, then a 12-bit counter and 62 random bits.

    The counter keeps identifiers created in the same millisecond strictly increasing.
    """
    global _v7_last
    with _v7_lock:
        ms = time.time_ns() // 1_000_000
        last_ms, last_seq = _v7_last
        if ms <= last_ms:
            ms, seq = last_ms, last_seq + 1
            if seq > 0xFFF:
                ms, seq = last_ms + 1, 0
        else:
            seq = secrets.randbits(11)
        _v7_last = (ms, seq)
    rand = int.from_bytes(os.urandom(8), "big") & ((1 << 62) - 1)
    value = (ms & ((1 << 48) - 1)) << 80 | 0x7 << 76 | seq << 64 | 0b10 << 62 | rand
    return uuid.UUID(int=value)


def new_record_id() -> str:
    return str(uuid7())


def new_output_id() -> str:
    return f"out-{uuid7()}"


def new_fork_id() -> str:
    return f"fork-{uuid7()}"


def hdt_id_for(national_id: str, key: bytes) -> str:
    """Pseudonymous HDT id: the first 12 hex digits of HMAC-SHA256(national id, key)."""
    digest = hmac.new(key, national_id.encode(), hashlib.sha256).hexdigest()
    return f"hdt-{digest[:12]}"


def episode_id(year: int, number: int) -> str:
    if not 0 <= number <= 999_999:
        raise ValueError("episode number must fit in 6 digits")
    return f"ep-{year:04d}-{number:06d}"


def instance_id(hdt_id: str, anatomy: str) -> str:
    """`inst-{hdt_id}-{uberon local id}`; non-UBERON anatomy keeps its local part after ':'."""
    local = anatomy.split(":", 1)[1] if ":" in anatomy else anatomy
    return f"inst-{hdt_id}-{local}"


def is_hdt_id(value: str) -> bool:
    return bool(HDT_ID_RE.match(value))


def is_episode_id(value: str) -> bool:
    return bool(EPISODE_ID_RE.match(value))
