"""Phone directory of the channels service: who a phone number belongs to.

Phone numbers are direct identifiers. They stay in this process; logs, audit records and
events carry only `tel-…` references (HMAC-SHA256 of the number).
"""

from __future__ import annotations

import hashlib
import hmac
import threading
from dataclasses import dataclass, replace

from atra.personas import PERSONAS


def phone_ref(phone: str, key: bytes) -> str:
    return "tel-" + hmac.new(key, phone.encode(), hashlib.sha256).hexdigest()[:12]


@dataclass(frozen=True)
class Contact:
    ref: str
    tenant_id: str
    language: str = "en"
    hdt_id: str | None = None
    staff_id: str | None = None


class Directory:
    def __init__(self, key: bytes) -> None:
        self.key = key
        self._lock = threading.Lock()
        self._by_phone: dict[str, Contact] = {}
        self._phone_of: dict[str, str] = {}

    def register(self, phone: str, *, tenant_id: str, language: str = "en",
                 hdt_id: str | None = None, staff_id: str | None = None) -> Contact:
        if (hdt_id is None) == (staff_id is None):
            raise ValueError("a phone belongs to one patient or one staff member")
        contact = Contact(phone_ref(phone, self.key), tenant_id, language, hdt_id, staff_id)
        with self._lock:
            self._by_phone[phone] = contact
            self._phone_of[hdt_id or staff_id or ""] = phone
        return contact

    def by_phone(self, phone: str) -> Contact | None:
        with self._lock:
            return self._by_phone.get(phone)

    def phone_of(self, person: str) -> str | None:
        """The phone of an `hdt_id` or a staff id."""
        with self._lock:
            return self._phone_of.get(person)

    def set_language(self, phone: str, language: str) -> None:
        with self._lock:
            contact = self._by_phone.get(phone)
            if contact is not None:
                self._by_phone[phone] = replace(contact, language=language)

    def ref(self, phone: str) -> str:
        return phone_ref(phone, self.key)


DEMO_STAFF = ("medical_officer.fac-a", "nurse.fac-a", "medical_officer.fac-b", "nurse.fac-b")


def demo_directory(key: bytes) -> Directory:
    """The demo personas and on-duty staff on fictitious numbers (+234 000 000 0nnn)."""
    d = Directory(key)
    for n, p in enumerate(PERSONAS, 1):
        d.register(f"+2340000000{n:03d}", tenant_id=p.tenant_id, language=p.language,
                   hdt_id=p.hdt_id)
    for n, staff in enumerate(DEMO_STAFF, 101):
        d.register(f"+2340000000{n:03d}", tenant_id=staff.split(".")[-1], staff_id=staff)
    return d
