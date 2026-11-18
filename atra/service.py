"""Shared building blocks of every FastAPI service (design 02 and 03).

- `create_app`: health, metrics, JWKS, RFC 9457 problem responses, tracing, the
  service's backends and audit log on `app.state`.
- `ToolExecutor`: one pipeline for a tool call, whichever surface it arrives on
  (REST `POST /v1/tools/{tool}` or MCP): identity, argument schema, policy decision,
  audit, handler, response schema, `_meta`.
- `mount_tools` and `mount_mcp`: the REST and MCP surfaces over one executor.
- `mount_a2a`: A2A agent cards and JSON-RPC endpoints.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from fastapi import APIRouter, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from atra import telemetry
from atra.backends import Backends
from atra.config import Settings
from atra.contracts import ModelRef, Role, ToolMeta
from atra.gateway import CallContext
from atra.policy import PolicyDecision
from atra.provenance import AuditLog
from atra.security import Claims, InvalidToken, TokenVerifier, bearer

PROBLEM_BASE = "https://atra.local/problems/"


class Problem(Exception):
    """An RFC 9457 problem: raised anywhere, rendered as `application/problem+json`."""

    def __init__(self, status: int, kind: str, detail: str, **extra: Any) -> None:
        super().__init__(detail)
        self.status, self.kind, self.detail, self.extra = status, kind, detail, extra

    def body(self, instance: str | None = None) -> dict[str, Any]:
        out = {"type": PROBLEM_BASE + self.kind, "title": self.kind.replace("-", " ").capitalize(),
               "status": self.status, "detail": self.detail, **self.extra}
        if instance:
            out["instance"] = instance
        return out


def problem_response(problem: Problem, instance: str | None = None) -> JSONResponse:
    return JSONResponse(problem.body(instance), status_code=problem.status,
                        media_type="application/problem+json")


@dataclass(frozen=True)
class Identity:
    """The verified caller of one request."""

    claims: Claims
    ctx: CallContext
    delegated: bool
    tenant_id: str | None


async def authenticate(headers: Mapping[str, str], verifier: TokenVerifier, *,
                       hdt_id: str | None = None) -> Identity:
    """Token check plus the `X-*` CallContext headers of design 03, 3.6.

    A user token acts as its own role; a service token acts for the human named in
    `X-Actor-Role` and `X-Actor-Id` (the APDT gateway delegating a clinician's call).
    """
    lower = {k.lower(): v for k, v in headers.items()}
    try:
        claims = verifier.verify(bearer(lower.get("authorization")))
    except InvalidToken as exc:
        raise Problem(401, "unauthenticated", str(exc)) from exc
    header_role = lower.get("x-actor-role")
    try:
        role = Role(header_role) if header_role else claims.role
    except ValueError:
        raise Problem(400, "bad-request", f"unknown role '{header_role}'") from None
    if claims.is_service:
        if role is None or not lower.get("x-actor-id"):
            raise Problem(400, "bad-request", "a service call must name the acting human")
        actor_id, delegated = lower["x-actor-id"], True
    else:
        if role is None or (claims.role is not None and role != claims.role):
            raise Problem(403, "forbidden", "the token does not carry this role")
        actor_id, delegated = claims.sub, False
    ctx = CallContext(hdt_id=hdt_id or claims.hdt_id or "", actor_role=role,
                      actor_id=actor_id, purpose=lower.get("x-purpose-of-use", "care"),
                      episode_id=lower.get("x-episode-id"), agent=lower.get("x-agent"))
    tenant = lower.get("x-tenant-id") if delegated else claims.tenant_id
    return Identity(claims, ctx, delegated, tenant or claims.tenant_id)


type AuditOutcome = Literal["ok", "denied", "degraded", "error"]
type ToolHandler = Callable[[BaseModel, Identity], Awaitable[Mapping[str, Any]]]
type Authoriser = Callable[[str, BaseModel, Identity], Awaitable[PolicyDecision]]


@dataclass
class ToolExecutor:
    """Runs tool calls through the same checks on every surface."""

    service: str
    version: str
    args: Mapping[str, type[BaseModel]]
    responses: Mapping[str, type[BaseModel]]
    handlers: dict[str, ToolHandler]
    authorise: Authoriser
    audit: AuditLog
    verifier: Callable[[], Awaitable[TokenVerifier]]
    descriptions: Mapping[str, str] = field(default_factory=dict)
    forced_fork: frozenset[str] = frozenset()

    @property
    def tools(self) -> list[str]:
        return list(self.args)

    async def identify(self, headers: Mapping[str, str], hdt_id: str | None) -> Identity:
        return await authenticate(headers, await self.verifier(), hdt_id=hdt_id)

    async def call(self, tool: str, raw: Mapping[str, Any],
                   headers: Mapping[str, str]) -> dict[str, Any]:
        if tool not in self.args:
            raise Problem(404, "unknown-tool", f"no tool named {tool}")
        hdt_id = raw.get("hdt_id") if isinstance(raw.get("hdt_id"), str) else None
        ident = await self.identify(headers, hdt_id)
        telemetry.bind(hdt_id=hdt_id, tenant_id=ident.tenant_id,
                       actor_role=ident.ctx.actor_role.value, agent=ident.ctx.agent)
        started = time.perf_counter()
        outcome = "error"
        try:
            with telemetry.tracer(self.service).start_as_current_span(f"tool {tool}") as span:
                span.set_attribute("atra.tool", tool)
                if tool in self.forced_fork and raw.get("fork") is False:
                    self._audit(tool, ident, "denied", "simulation on live model state")
                    outcome = "denied"
                    raise Problem(403, "forbidden",
                                  "simulation on live model state is not permitted")
                try:
                    args = self.args[tool].model_validate(dict(raw))
                except ValidationError as exc:
                    outcome = "invalid"
                    raise Problem(422, "invalid-arguments", _short(exc)) from exc
                decision = await self.authorise(tool, args, ident)
                if not decision.allow:
                    self._audit(tool, ident, "denied", decision.reason)
                    outcome = "denied"
                    raise Problem(403, "forbidden", decision.reason or "denied by policy")
                result = dict(await self.handlers[tool](args, ident))
                meta = dict(result.pop("_meta", {}))
                try:
                    data = self.responses[tool].model_validate(result)
                except ValidationError as exc:
                    self._audit(tool, ident, "error", "response failed its schema")
                    raise Problem(500, "contract-violation",
                                  f"{tool} response failed its schema: {_short(exc)}") from exc
                body = data.model_dump(mode="json", by_alias=True, exclude_none=True)
                body["_meta"] = ToolMeta.model_validate(
                    {"ahdt_version": self.version, **meta}).model_dump(
                        mode="json", by_alias=True, exclude_none=True)
                self._audit(tool, ident, "ok", None, trace_id=telemetry.current_trace_id())
                outcome = "ok"
                return body
        finally:
            m = telemetry.metrics()
            m.tool_calls.labels(tool=tool, outcome=outcome).inc()
            m.tool_latency.labels(tool=tool).observe(time.perf_counter() - started)

    def _audit(self, tool: str, ident: Identity, outcome: AuditOutcome, reason: str | None,
               trace_id: str | None = None) -> None:
        self.audit.append(actor={"id": ident.ctx.actor_id, "role": ident.ctx.actor_role.value},
                          agent=ident.ctx.agent, hdt_id=ident.ctx.hdt_id or None,
                          tenant_id=ident.tenant_id, episode_id=ident.ctx.episode_id,
                          action="tool", target=tool, purpose=ident.ctx.purpose,
                          outcome=outcome, reason=reason,
                          trace_id=trace_id or telemetry.current_trace_id())


def _short(exc: ValidationError) -> str:
    return "; ".join(f"{'.'.join(str(p) for p in e['loc']) or '(body)'}: {e['msg']}"
                     for e in exc.errors()[:5])


def meta(*models: tuple[str, str], **extra: Any) -> dict[str, Any]:
    """`_meta` for a handler result: the model versions used, plus any other fields."""
    return {"models": [ModelRef(model_id=m, version=v).model_dump() for m, v in models], **extra}


# ---------------------------------------------------------------------------
# Surfaces
# ---------------------------------------------------------------------------

COMPONENTS = "#/components/schemas/{model}"


def mount_tools(app: FastAPI, executor: ToolExecutor, *, prefix: str = "/v1/tools") -> None:
    from pydantic.json_schema import models_json_schema

    router = APIRouter(prefix=prefix, tags=["tools"])
    mode: Literal["validation"] = "validation"
    models = [(m, mode) for m in (*executor.args.values(), *executor.responses.values())]
    refs, top = models_json_schema(models, by_alias=True, ref_template=COMPONENTS)
    add_component_schemas(app, top.get("$defs", {}))
    for tool in executor.tools:
        _add_tool_route(router, executor, tool,
                        refs[(executor.args[tool], "validation")],
                        refs[(executor.responses[tool], "validation")])
    app.include_router(router)


def add_component_schemas(app: FastAPI, schemas: Mapping[str, Any]) -> None:
    """Schemas the tool routes refer to, merged into the app's OpenAPI `components`."""
    store: dict[str, Any] = app.state.component_schemas
    for name, schema in schemas.items():
        if name in store and store[name] != schema:
            raise ValueError(f"two different OpenAPI schemas are named {name}")
        store[name] = schema


def _add_tool_route(router: APIRouter, executor: ToolExecutor, tool: str,
                    request_schema: Mapping[str, Any], response_schema: Mapping[str, Any]
                    ) -> None:
    async def endpoint(request: Request) -> JSONResponse:
        try:
            raw = await request.json()
        except ValueError:
            raise Problem(400, "bad-request", "the body is not JSON") from None
        if not isinstance(raw, dict):
            raise Problem(400, "bad-request", "the body must be a JSON object")
        return JSONResponse(await executor.call(tool, raw, dict(request.headers)))

    router.add_api_route(
        f"/{tool}", endpoint, methods=["POST"], name=tool,
        summary=executor.descriptions.get(tool, tool),
        openapi_extra={
            "requestBody": {"required": True,
                            "content": {"application/json": {"schema": dict(request_schema)}}},
            "responses": {"200": {"description": "Tool result",
                                  "content": {"application/json": {
                                      "schema": dict(response_schema)}}}}},
    )


class McpMount:
    """One MCP server (streamable HTTP, stateless) over a subset of an executor's tools."""

    def __init__(self, name: str, executor: ToolExecutor, tools: Sequence[str],
                 descriptors: Mapping[str, Mapping[str, Any]]) -> None:
        import mcp_types as types
        from mcp.server.lowlevel import Server

        self.name, self.executor, self.tools = name, executor, list(tools)

        async def list_tools(ctx: Any, params: Any) -> Any:
            return types.ListToolsResult(tools=[
                types.Tool(name=t, description=descriptors[t].get("description", t),
                           input_schema=dict(descriptors[t]["inputSchema"]),
                           output_schema=dict(descriptors[t].get("outputSchema") or {}) or None)
                for t in self.tools])

        async def call_tool(ctx: Any, params: Any) -> Any:
            headers = dict(ctx.request.headers) if ctx.request is not None else {}
            if params.name not in self.tools:
                return _mcp_error(types, Problem(404, "unknown-tool", params.name))
            try:
                body = await executor.call(params.name, params.arguments or {}, headers)
            except Problem as problem:
                return _mcp_error(types, problem)
            return types.CallToolResult(content=[types.TextContent(type="text", text="ok")],
                                        structured_content=body)

        self.server = Server(name, version=executor.version, on_list_tools=list_tools,
                             on_call_tool=call_tool)
        self.app = self.server.streamable_http_app(streamable_http_path="/", stateless_http=True,
                                                   json_response=True)

    def lifespan(self) -> contextlib.AbstractAsyncContextManager[None]:
        return self.server.session_manager.run()  # type: ignore[no-any-return]


def _mcp_error(types: Any, problem: Problem) -> Any:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=problem.detail)], is_error=True,
        structured_content={"error": problem.body()})


def mount_mcp(app: FastAPI, path: str, mount: McpMount) -> None:
    app.mount(path, mount.app)
    app.state.mcp_mounts.append(mount)


@dataclass(frozen=True)
class SkillSpec:
    id: str
    description: str


type SkillHandler = Callable[[str, Mapping[str, Any]], Awaitable[Any]]


def mount_a2a(app: FastAPI, base_url: str, name: str, description: str,
              skills: Iterable[SkillSpec], handler: SkillHandler, *, version: str) -> None:
    """One A2A agent at `/a2a/<name>/` with its card at `/.well-known/agent-card.json`.

    A request message carries a data part `{"skill": <id>, "args": {...}}`; the reply is a
    data message with the skill's result.
    """
    from a2a.helpers.proto_helpers import get_data_parts, new_data_message
    from a2a.server.agent_execution import AgentExecutor, RequestContext
    from a2a.server.events import EventQueue
    from a2a.server.request_handlers import DefaultRequestHandler
    from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes
    from a2a.server.tasks import InMemoryTaskStore
    from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill
    from starlette.applications import Starlette

    skill_list = list(skills)
    known = {s.id for s in skill_list}
    card = AgentCard(
        name=name, description=description, version=version,
        supported_interfaces=[AgentInterface(url=f"{base_url}/a2a/{name}/",
                                             protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=False),
        default_input_modes=["application/json"], default_output_modes=["application/json"],
        skills=[AgentSkill(id=s.id, name=s.id, description=s.description, tags=[name])
                for s in skill_list])

    class Executor(AgentExecutor):  # type: ignore[misc]
        async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
            parts = get_data_parts(context.message.parts) if context.message else []
            request = parts[0] if parts and isinstance(parts[0], Mapping) else {}
            skill = str(request.get("skill", ""))
            if skill not in known:
                result: Any = {"error": f"unknown skill '{skill}'", "skills": sorted(known)}
            else:
                result = await handler(skill, dict(request.get("args") or {}))
            await event_queue.enqueue_event(new_data_message(result,
                                                             context_id=context.context_id))

        async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
            return None

    request_handler = DefaultRequestHandler(agent_executor=Executor(),
                                            task_store=InMemoryTaskStore(), agent_card=card)
    sub = Starlette(routes=[*create_agent_card_routes(card),
                            *create_jsonrpc_routes(request_handler, rpc_url="/")])
    app.mount(f"/a2a/{name}", sub)
    app.state.a2a_cards.append(name)


# ---------------------------------------------------------------------------
# Application factory
# ---------------------------------------------------------------------------

def create_app(service: str, settings: Settings, *, title: str, description: str,
               backends: Backends | None = None, version: str = "1.0.0",
               on_startup: Callable[[FastAPI], Awaitable[None]] | None = None,
               on_shutdown: Callable[[FastAPI], Awaitable[None]] | None = None) -> FastAPI:
    telemetry.setup(service, otlp_endpoint=None if settings.backend.trace == "memory"
                    else settings.infra.otlp)
    backends = backends or Backends(settings, service)

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with contextlib.AsyncExitStack() as stack:
            for mount in app.state.mcp_mounts:
                await stack.enter_async_context(mount.lifespan())
            if on_startup is not None:
                await on_startup(app)
            try:
                yield
            finally:
                if on_shutdown is not None:
                    await on_shutdown(app)
                await backends.close()

    app = FastAPI(title=title, description=description, version=version, lifespan=lifespan)
    if settings.security.cors_origins:
        from fastapi.middleware.cors import CORSMiddleware

        # The Flutter web builds call the APIs from their own origin.
        app.add_middleware(CORSMiddleware, allow_origins=settings.security.cors_origins,
                           allow_methods=["*"], allow_headers=["*"])
    app.state.service = service
    app.state.settings = settings
    app.state.backends = backends
    app.state.audit = AuditLog(service, path=None if backends.ephemeral
                               else settings.var_dir / "audit" / f"{service}.jsonl")
    app.state.mcp_mounts = []
    app.state.a2a_cards = []
    app.state.component_schemas = {}
    generate = app.openapi

    def openapi() -> dict[str, Any]:
        spec = generate()
        schemas = spec.setdefault("components", {}).setdefault("schemas", {})
        for name, schema in app.state.component_schemas.items():
            if name in schemas and schemas[name] != schema:
                raise ValueError(f"two different OpenAPI schemas are named {name}")
            schemas[name] = schema
        return spec

    app.openapi = openapi  # type: ignore[method-assign]

    @app.exception_handler(Problem)
    async def _problem(request: Request, exc: Problem) -> JSONResponse:
        return problem_response(exc, str(request.url.path))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        kind = {401: "unauthenticated", 403: "forbidden", 404: "not-found",
                405: "method-not-allowed"}.get(exc.status_code, "http-error")
        return problem_response(Problem(exc.status_code, kind, str(exc.detail)),
                                str(request.url.path))

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
        detail = "; ".join(f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                           for e in exc.errors()[:5])
        return problem_response(Problem(422, "invalid-request", detail), str(request.url.path))

    @app.get("/health", tags=["operations"])
    async def health() -> dict[str, Any]:
        return {"service": service, "status": "ok", "profile": settings.profile,
                "version": version}

    @app.get("/metrics", tags=["operations"], include_in_schema=False)
    async def prometheus() -> Response:
        from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

        return Response(generate_latest(telemetry.metrics().registry),
                        media_type=CONTENT_TYPE_LATEST)

    @app.get("/.well-known/jwks.json", tags=["operations"])
    async def jwks() -> dict[str, Any]:
        return backends.issuer.jwks()

    return app


async def verifier_of(app: FastAPI) -> TokenVerifier:
    cached = getattr(app.state, "verifier", None)
    if cached is None:
        cached = await app.state.backends.identity.verifier()
        app.state.verifier = cached
    return cached  # type: ignore[no-any-return]
