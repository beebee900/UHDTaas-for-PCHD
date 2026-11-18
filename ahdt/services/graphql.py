# mypy: disable-error-code="call-arg, untyped-decorator"
"""GraphQL surface over the same tool executor (design 04, 4.7.2).

    person(hdtId) { twins { kind status state } observations(codes, period) conditions
                    medications }

Every field calls a tool through `ToolExecutor`, so identity, policy, audit and metrics are
those of REST and MCP.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import strawberry
from fastapi import FastAPI, Request
from strawberry.fastapi import GraphQLRouter
from strawberry.scalars import JSON
from strawberry.types import Info

from atra.connectors import DTKind
from atra.service import Problem, ToolExecutor

TWIN_KINDS = tuple(k.value for k in DTKind if k.is_ahdt_member and k is not DTKind.POPULATION)


@strawberry.type
class Twin:
    kind: str
    status: str
    state: JSON


@strawberry.type
class SeriesPoint:
    t: datetime
    v: JSON
    unit: str
    quality: str


@strawberry.type
class Series:
    code: str
    points: list[SeriesPoint]


@strawberry.input
class PeriodInput:
    start: datetime
    end: datetime


async def _call(info: Info, tool: str, args: dict[str, Any]) -> dict[str, Any]:
    ctx = info.context
    try:
        result: dict[str, Any] = await ctx["executor"].call(tool, args, ctx["headers"])
    except Problem as exc:
        raise ValueError(f"{exc.kind}: {exc.detail}") from exc
    return result


@strawberry.type
class Person:
    hdt_id: str

    @strawberry.field
    async def twins(self, info: Info, kinds: list[str] | None = None) -> list[Twin]:
        out = []
        for kind in kinds or TWIN_KINDS:
            body = await _call(info, "ahdt.model.state", {"hdt_id": self.hdt_id, "dt": kind})
            out.append(Twin(kind=kind, status=body["status"], state=body["state"]))
        return out

    @strawberry.field
    async def observations(self, info: Info, codes: list[str],
                           period: PeriodInput | None = None) -> list[Series]:
        args: dict[str, Any] = {"hdt_id": self.hdt_id, "codes": codes}
        if period:
            args["period"] = {"start": period.start.isoformat(), "end": period.end.isoformat()}
        body = await _call(info, "ahdt.data.observations", args)
        return [Series(code=code, points=[SeriesPoint(
            t=datetime.fromisoformat(p["t"]), v=p["v"], unit=p["unit"],
            quality=p.get("quality", "ok")) for p in points])
            for code, points in body["series"].items()]

    @strawberry.field
    async def conditions(self, info: Info) -> list[JSON]:
        body = await _call(info, "ahdt.data.knowledge", {
            "hdt_id": self.hdt_id, "query_id": "person.conditions", "params": {}})
        return list(body["rows"])

    @strawberry.field
    async def medications(self, info: Info, active_only: bool = False) -> list[JSON]:
        body = await _call(info, "ahdt.data.medications",
                           {"hdt_id": self.hdt_id, "active_only": active_only})
        return list(body["medications"])


@strawberry.type
class Query:
    @strawberry.field
    def person(self, hdt_id: str) -> Person:
        return Person(hdt_id=hdt_id)


schema = strawberry.Schema(query=Query)


def mount_graphql(app: FastAPI, executor: ToolExecutor, path: str = "/graphql") -> None:
    async def context(request: Request) -> dict[str, Any]:
        return {"executor": executor, "headers": dict(request.headers)}

    app.include_router(GraphQLRouter(schema, context_getter=context), prefix=path,
                       include_in_schema=False)
