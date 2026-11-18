"""Step 4 of the pipeline: pseudonymisation and consent (design 04, 4.3.1).

A direct identifier never leaves this module: it is replaced by the `hdt_id` derived with
HMAC-SHA256, and the pair is kept only in the identity table.
"""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select

from ahdt.stores import tables
from atra.backends.base import RelationalBackend
from atra.contracts import PurposeOfUse
from atra.gateway import PatientConsent
from atra.ids import hdt_id_for


class Pseudonymiser:
    def __init__(self, db: RelationalBackend, key: bytes) -> None:
        self.db = db
        self.key = key

    async def hdt_id(self, system: str, value: str) -> str:
        async with self.db.engine().begin() as conn:
            row = (await conn.execute(select(tables.identity.c.hdt_id).where(
                tables.identity.c.system == system,
                tables.identity.c.value == value))).first()
            if row is not None:
                return str(row[0])
            hdt_id = hdt_id_for(f"{system}|{value}", self.key)
            await conn.execute(tables.identity.insert().values(
                system=system, value=value, hdt_id=hdt_id))
            return hdt_id


def consent_tag(consent: PatientConsent | None) -> str | None:
    """The purposes a record may serve, or None when care itself is not consented."""
    if consent is None or PurposeOfUse.CARE.value not in consent.purposes:
        return None
    return _tag(consent.purposes)


def _tag(purposes: Iterable[str]) -> str:
    return "+".join(sorted(str(p) for p in purposes))
