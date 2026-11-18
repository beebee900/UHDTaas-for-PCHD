"""Demo users: one per role per tenant, plus the personas' patient, person and proxy logins.

    python -m atra.demo_users

writes random passwords to `deploy/keycloak/demo-users.local.env` (never committed, never
printed), a table of user names, roles and passwords to `deploy/keycloak/demo-logins.local.txt`,
and password hashes to `var/keys/demo-users.json` for the local issuer (p0).
The Keycloak realm import (WP30) reads the same env file.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from pathlib import Path

from atra.config import ROOT, Settings, get_settings
from atra.contracts import Role
from atra.personas import PERSONAS

ENV_FILE = ROOT / "deploy" / "keycloak" / "demo-users.local.env"
LOGINS_NAME = "demo-logins.local.txt"

STAFF_ROLES = (Role.MEDICAL_OFFICER, Role.RADIOLOGIST, Role.PHARMACIST, Role.NURSE,
               Role.LAB_SCIENTIST, Role.COMMUNITY_HEALTH_WORKER, Role.THERAPIST,
               Role.CLINICAL_SAFETY_OFFICER, Role.ADMINISTRATOR)
PLATFORM_ROLES = (Role.RESEARCHER, Role.PUBLIC_HEALTH_OFFICIAL)
CHILD_AGE = 16


@dataclass(frozen=True)
class DemoUser:
    username: str
    role: Role
    tenant_id: str | None = None
    hdt_id: str | None = None
    proxy_for: tuple[str, ...] = field(default_factory=tuple)
    carer_for: tuple[str, ...] = field(default_factory=tuple)


def demo_users() -> list[DemoUser]:
    users = [DemoUser(f"{r.value}.{t}", r, t) for t in ("fac-a", "fac-b") for r in STAFF_ROLES]
    users += [DemoUser(r.value, r) for r in PLATFORM_ROLES]
    for p in PERSONAS:
        users.append(DemoUser(f"person.{p.key}", Role.PERSON, hdt_id=p.hdt_id))
        if p.age_years < CHILD_AGE:
            users.append(DemoUser(f"proxy.{p.key}", Role.PROXY, p.tenant_id,
                                  proxy_for=(p.hdt_id,)))
        else:
            users.append(DemoUser(f"patient.{p.key}", Role.PATIENT, p.tenant_id, hdt_id=p.hdt_id))
        users.append(DemoUser(f"carer.{p.key}", Role.CARER, carer_for=(p.hdt_id,)))
    return users


def _hash(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1).hex()


class UserStore:
    """Password check for the local issuer."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._users: dict[str, dict[str, object]] = (
            json.loads(path.read_text(encoding="utf-8")) if path.exists() else {})

    def check(self, username: str, password: str) -> DemoUser | None:
        rec = self._users.get(username)
        if rec is None:
            return None
        expected = str(rec["hash"])
        if not hmac.compare_digest(_hash(password, bytes.fromhex(str(rec["salt"]))), expected):
            return None
        u = dict(rec["user"])  # type: ignore[call-overload]
        return DemoUser(u["username"], Role(u["role"]), u.get("tenant_id"), u.get("hdt_id"),
                        tuple(u.get("proxy_for", ())), tuple(u.get("carer_for", ())))


def write(settings: Settings | None = None, *, env_file: Path = ENV_FILE) -> Path:
    settings = settings or get_settings()
    store_path = settings.var_dir / "keys" / "demo-users.json"
    store: dict[str, dict[str, object]] = {}
    lines = ["# Demo user passwords. Local only: never commit or share this file."]
    table = ["Demo logins. Local only: never commit or share this file.", "",
             f"{'username':<34}{'role':<26}password"]
    for user in demo_users():
        password = secrets.token_urlsafe(12)
        salt = os.urandom(16)
        record = asdict(user)
        record["role"] = user.role.value
        store[user.username] = {"salt": salt.hex(), "hash": _hash(password, salt), "user": record}
        key = user.username.upper().replace(".", "_").replace("-", "_")
        lines.append(f"DEMO_USER_{key}={password}")
        table.append(f"{user.username:<34}{user.role.value:<26}{password}")
    outputs = ((store_path, json.dumps(store, indent=1)), (env_file, "\n".join(lines) + "\n"),
               (env_file.parent / LOGINS_NAME, "\n".join(table) + "\n"))
    for path, text in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        path.chmod(0o600)
    return env_file


if __name__ == "__main__":
    out = write()
    logins = (out.parent / LOGINS_NAME).relative_to(ROOT)
    print(f"wrote {len(demo_users())} demo users; user names and passwords are in {logins}")
