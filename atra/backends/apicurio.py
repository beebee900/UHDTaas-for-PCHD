"""Apicurio Registry 3 client for the connector contracts (profile p1, design 02, 2.3).

Uses the core registry API v3 (`/apis/registry/v3`) of `apicurio/apicurio-registry:3.0.9`:
one artifact per contract in group `atra.connectors`, artifact type `JSON` (JSON Schema),
one artifact version per contract version.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any
from urllib.parse import quote

import httpx

from atra.backends.base import SchemaRegistryBackend

GROUP = "atra.connectors"


def _semver_key(version: str) -> tuple[int, ...]:
    return tuple(int(p) if p.isdigit() else 0 for p in version.split("."))


class ApicurioSchemaRegistry(SchemaRegistryBackend):
    def __init__(self, base_url: str, *, group: str = GROUP, timeout_s: float = 5.0,
                 client: httpx.AsyncClient | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self.group = group
        self._client = client or httpx.AsyncClient(timeout=timeout_s)

    def _artifact(self, subject: str) -> str:
        return (f"{self.base_url}/groups/{quote(self.group, safe='')}"
                f"/artifacts/{quote(subject, safe='')}")

    async def get(self, subject: str, version: str) -> dict[str, Any]:
        resp = await self._client.get(
            f"{self._artifact(subject)}/versions/{quote(version, safe='')}/content")
        if resp.status_code == 404:
            raise KeyError(f"{subject} v{version}")
        resp.raise_for_status()
        result: dict[str, Any] = resp.json()
        return result

    async def register(self, subject: str, version: str, schema: Mapping[str, Any]) -> None:
        body = {"artifactId": subject, "artifactType": "JSON",
                "firstVersion": {"version": version, "content": {
                    "content": json.dumps(schema, sort_keys=True),
                    "contentType": "application/json"}}}
        resp = await self._client.post(
            f"{self.base_url}/groups/{quote(self.group, safe='')}/artifacts",
            params={"ifExists": "FIND_OR_CREATE_VERSION"}, json=body)
        resp.raise_for_status()

    async def versions(self, subject: str) -> list[str]:
        resp = await self._client.get(f"{self._artifact(subject)}/versions",
                                      params={"limit": 1000})
        if resp.status_code == 404:
            return []
        resp.raise_for_status()
        found = [str(v["version"]) for v in resp.json().get("versions", [])]
        return sorted(found, key=_semver_key)

    async def aclose(self) -> None:
        await self._client.aclose()
