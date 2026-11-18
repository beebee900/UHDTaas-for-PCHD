"""The six demo personas (design 06, section 6.4.2). Initials only; none is a real person.

The `hdt_id` of each persona is derived from a synthetic national identifier with the
demo HMAC key, so every service and the synthetic population agree on it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from atra.ids import hdt_id_for

DEMO_HDT_KEY = b"atra-demo-hdt-key"


@dataclass(frozen=True)
class Persona:
    key: str
    initials: str
    sex: Literal["female", "male"]
    age_years: int
    language: Literal["en", "yo", "ha", "ig", "pcm"]
    tenant_id: Literal["fac-a", "fac-b"]
    scenario: str
    synthetic_national_id: str
    withheld_tools: frozenset[str] = frozenset()

    @property
    def hdt_id(self) -> str:
        return hdt_id_for(self.synthetic_national_id, DEMO_HDT_KEY)


PERSONAS: tuple[Persona, ...] = (
    Persona("ao", "A.O.", "female", 47, "yo", "fac-a", "uncomplicated malaria",
            "SYN-NG-0000000001"),
    Persona("bm", "B.M.", "male", 8, "ha", "fac-a",
            "severe malaria with falling consciousness and hypoglycaemia", "SYN-NG-0000000002"),
    Persona("cn", "C.N.", "female", 29, "ig", "fac-a", "pyelonephritis at 22 weeks pregnancy",
            "SYN-NG-0000000003"),
    Persona("de", "D.E.", "male", 58, "pcm", "fac-b",
            "hypertension, type 2 diabetes and CKD stage 3", "SYN-NG-0000000004"),
    Persona("ef", "E.F.", "female", 19, "yo", "fac-a", "sickle cell vaso-occlusive crisis",
            "SYN-NG-0000000005"),
    Persona("gh", "G.H.", "male", 35, "en", "fac-b", "TB work-up while on ART",
            "SYN-NG-0000000006", withheld_tools=frozenset({"ahdt.data.genome"})),
)

BY_KEY = {p.key: p for p in PERSONAS}
BY_HDT = {p.hdt_id: p for p in PERSONAS}
