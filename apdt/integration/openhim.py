"""OpenHIM client: mediator registration, heartbeats, channels and routing (design 05, 5.3).

API as documented at https://openhim.org/docs/dev-guide/developing-mediators and
https://openhim.org/docs/api/introduction/authentication, with routes and models from
openhim-core-js (`src/koaApi.js`, `src/model/channels.js`, commit b62a2e4dbd):

- `POST /mediators` with `{urn, version, name, defaultChannelConfig, endpoints, configDefs,
  config}`; at least one endpoint
- `POST /mediators/{urn}/heartbeat` with `{uptime, config?}`; the reply body is the
  mediator config when it changed (or `config: true` was sent), else empty
- `POST /mediators/{urn}/channels` with a list of channel names installs those default
  channels
- `GET`/`POST /channels`, `GET /transactions`
- Basic authentication on every API request

The router (the port OpenHIM listens on for client traffic) is a separate base URL.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import quote

import httpx

MEDIATOR_URN = "urn:openhim-mediator:atra-apdt"
JSON_OPENHIM = "application/json+openhim"


def route(name: str, host: str, port: int, path: str, *, primary: bool = True,
          secured: bool = False) -> dict[str, Any]:
    """A route object (`RouteDef` of openhim-core-js)."""
    return {"name": name, "type": "http", "host": host, "port": port, "path": path,
            "primary": primary, "secured": secured}


def channel(name: str, url_pattern: str, routes: Sequence[Mapping[str, Any]], *,
            allow: Sequence[str], methods: Sequence[str] = ("POST",),
            description: str = "") -> dict[str, Any]:
    """A channel object (`ChannelDef` of openhim-core-js)."""
    return {"name": name, "description": description, "urlPattern": url_pattern,
            "methods": list(methods), "type": "http", "allow": list(allow),
            "authType": "private", "routes": [dict(r) for r in routes], "status": "enabled"}


def atra_mediator(apdt_host: str, apdt_port: int, *, version: str = "1.0.0",
                  client_role: str = "atra-facility") -> dict[str, Any]:
    """The APDT registered as an OpenHIM mediator, with the HIE channels between the two
    demo facilities and the HL7 v2 feed of each."""
    channels = []
    for tenant in ("fac-a", "fac-b"):
        channels.append(channel(
            f"ATRA referral to {tenant}", f"^/referral/{tenant}$",
            [route(f"APDT {tenant} referral", apdt_host, apdt_port,
                   f"/v1/t/{tenant}/integration/referral")],
            allow=[client_role], description=f"Referral and discharge bundles for {tenant}"))
        channels.append(channel(
            f"ATRA HL7 v2 feed {tenant}", f"^/hl7v2/{tenant}$",
            [route(f"APDT {tenant} HL7 v2", apdt_host, apdt_port,
                   f"/v1/t/{tenant}/integration/hl7v2")],
            allow=[client_role], description=f"Lab and ADT feed of {tenant}"))
    return {"urn": MEDIATOR_URN, "version": version, "name": "ATRA APDT",
            "description": "APDT integration inbox and HIE endpoints",
            "endpoints": [route("APDT", apdt_host, apdt_port, "/health")],
            "defaultChannelConfig": channels}


class OpenHimClient:
    def __init__(self, api_url: str, username: str, password: str, *, router_url: str = "",
                 transport: httpx.AsyncBaseTransport | None = None,
                 verify: bool = True) -> None:
        self.api = httpx.AsyncClient(base_url=api_url, auth=(username, password),
                                     transport=transport, verify=verify, timeout=30)
        self.router = httpx.AsyncClient(base_url=router_url or api_url,
                                        auth=(username, password), transport=transport,
                                        verify=verify, timeout=30)

    async def aclose(self) -> None:
        await self.api.aclose()
        await self.router.aclose()

    async def register(self, mediator: Mapping[str, Any]) -> None:
        if not mediator.get("endpoints"):
            raise ValueError("a mediator needs at least one endpoint")
        (await self.api.post("/mediators", json=dict(mediator))).raise_for_status()

    async def heartbeat(self, urn: str, uptime_s: float, *,
                        want_config: bool = False) -> dict[str, Any] | None:
        body: dict[str, Any] = {"uptime": uptime_s}
        if want_config:
            body["config"] = True
        resp = await self.api.post(f"/mediators/{quote(urn, safe='')}/heartbeat", json=body)
        resp.raise_for_status()
        return resp.json() if resp.content else None

    async def install_default_channels(self, urn: str, names: Sequence[str]) -> None:
        """Installs the named channels of the mediator's `defaultChannelConfig`."""
        (await self.api.post(f"/mediators/{quote(urn, safe='')}/channels",
                             json=list(names))).raise_for_status()

    async def channels(self) -> list[dict[str, Any]]:
        resp = await self.api.get("/channels")
        resp.raise_for_status()
        return list(resp.json())

    async def add_channel(self, body: Mapping[str, Any]) -> None:
        (await self.api.post("/channels", json=dict(body))).raise_for_status()

    async def transactions(self) -> list[dict[str, Any]]:
        resp = await self.api.get("/transactions")
        resp.raise_for_status()
        return list(resp.json())

    async def send(self, path: str, body: Mapping[str, Any] | str, *,
                   content_type: str = "application/fhir+json",
                   headers: Mapping[str, str] | None = None) -> httpx.Response:
        """Client traffic through the OpenHIM router (logged as a transaction there)."""
        content = body if isinstance(body, str) else json.dumps(body)
        resp = await self.router.post(path, content=content,
                                      headers={"content-type": content_type, **(headers or {})})
        resp.raise_for_status()
        return resp


def mediator_response(urn: str, status: str, response: Mapping[str, Any], *,
                      orchestrations: Sequence[Mapping[str, Any]] = (),
                      properties: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The structured reply a mediator returns with content type `application/json+openhim`."""
    allowed = ("Processing", "Failed", "Completed", "Successful", "Completed with error(s)")
    if status not in allowed:
        raise ValueError(f"status must be one of {allowed}")
    out: dict[str, Any] = {"x-mediator-urn": urn, "status": status, "response": dict(response)}
    if orchestrations:
        out["orchestrations"] = [dict(o) for o in orchestrations]
    if properties:
        out["properties"] = dict(properties)
    return out
