"""The channels service's client of the APDT API (design 03, 3.7).

Calls carry a service token of `channels-svc` and name the patient as the acting human
(`X-Actor-Role: patient`, `X-Actor-Id: patient:<hdt_id>`), as design 03, 3.6 defines for a
service acting for a person. The W3C `traceparent` header carries the trace to the APDT.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

import httpx
from opentelemetry.propagate import inject


class ApdtError(RuntimeError):
    pass


class ApdtClient:
    def __init__(self, base_url: str, token: Callable[[], str], *,
                 transport: httpx.AsyncBaseTransport | None = None) -> None:
        self.http = httpx.AsyncClient(base_url=base_url, transport=transport, timeout=30)
        self.token = token

    async def aclose(self) -> None:
        await self.http.aclose()

    def _headers(self, hdt_id: str | None, tenant_id: str) -> dict[str, str]:
        h = {"authorization": f"Bearer {self.token()}", "x-tenant-id": tenant_id,
             "x-purpose-of-use": "care"}
        if hdt_id:
            h.update({"x-actor-role": "patient", "x-actor-id": f"patient:{hdt_id}"})
        inject(h)
        return h

    async def _call(self, method: str, path: str, *, hdt_id: str | None, tenant_id: str,
                    body: Any) -> dict[str, Any]:
        try:
            resp = await self.http.request(method, path, json=body,
                                           headers=self._headers(hdt_id, tenant_id))
        except httpx.HTTPError as exc:
            raise ApdtError(str(exc)) from exc
        if resp.status_code >= 400:
            raise ApdtError(f"{method} {path}: {resp.status_code} {resp.text[:200]}")
        return dict(resp.json())

    async def put_consent(self, tenant_id: str, hdt_id: str,
                          consent: Mapping[str, Any]) -> dict[str, Any]:
        return await self._call("PUT", f"/v1/t/{tenant_id}/patients/{hdt_id}/consent",
                                hdt_id=hdt_id, tenant_id=tenant_id, body=dict(consent))

    async def post_message(self, tenant_id: str, hdt_id: str, text: str, *, language: str,
                           channel: str) -> dict[str, Any]:
        return await self._call("POST", f"/v1/t/{tenant_id}/patients/{hdt_id}/messages",
                                hdt_id=hdt_id, tenant_id=tenant_id,
                                body={"text": text, "language": language, "channel": channel})

    async def file_bundle(self, tenant_id: str, bundle: Mapping[str, Any]) -> dict[str, Any]:
        return await self._call("POST", f"/v1/t/{tenant_id}/integration/fhir", hdt_id=None,
                                tenant_id=tenant_id, body=dict(bundle))
