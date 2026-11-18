"""
atra.gateway
============

Agentic Patient Digital Twin (APDT) integration with the Agentic Human Digital Twin
(AHDT), following the revised ATRA Layer 6:

    6.1 Data services            -> AHDT Layer 3
    6.2 AI/ML/Simulation services -> AHDT Layer 4
    6.3 XAI services              -> AHDT Layer 5
    6.4 Cognitive services
    6.5 Connection services       (Connector objects, see atra.connectors)

Two integration mechanisms:

1. AHDTServiceGateway - on-demand access. APDT agents call AHDT Layer 6.1-6.4
   operations as named tools (query, forecast, simulate, explain, converse). Every
   call is checked against the acting clinician's role, the patient's consent and
   the purpose of use; simulation is always forced onto forked model instances.

2. Connectors (Layer 6.5) - continuous, contracted transfer:
   * ClinicalFindingWriteBackConnector   APDT -> AHDT Whole-Body DT (signed findings only)
   * DeteriorationEventConnector         AHDT Whole-Body DT -> APDT (early-warning events)

Only the standard library is required. MCPBackend imports the MCP SDK lazily.

Run the demo:   python -m atra.gateway
Run the tests:  python -m pytest tests/unit/atra/test_gateway.py -q
"""

from __future__ import annotations

import abc
import asyncio
import enum
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, FrozenSet, List, Mapping, Optional, Tuple

from atra.connectors import (
    Connector,
    DataContract,
    Direction,
    DTKind,
    FieldSpec,
    SyncMode,
)

__all__ = [
    "ToolSpec", "AHDT_TOOLS", "Role", "DEFAULT_ROLE_TOOLS", "CallContext", "GatewayDenied",
    "PatientConsent", "AHDTBackend", "InMemoryAHDTBackend", "MCPBackend", "RESTBackend",
    "AHDTRefused", "ToolResult", "AHDTServiceGateway", "ClinicalFindingWriteBackConnector",
    "DeteriorationEventConnector",
]


# ---------------------------------------------------------------------------
# 1. Tool catalogue: AHDT Layer 6.1-6.4 operations exposed to the APDT
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ToolSpec:
    name: str
    sublayer: str                    # AHDT service sublayer: "6.1" .. "6.4"
    reaches_layer: Optional[int]     # AHDT layer the tool gives access to (3, 4, 5) or None
    description: str
    required_args: Tuple[str, ...] = ()
    cacheable: bool = True
    forces_fork: bool = False        # simulation must run on forked model instances

    def descriptor(self) -> Dict[str, Any]:
        """MCP-style tool descriptor that agent frameworks can register directly."""
        return {"name": self.name, "description": f"[AHDT {self.sublayer}] {self.description}",
                "inputSchema": {"type": "object",
                                "properties": {a: {} for a in self.required_args},
                                "required": list(self.required_args)}}


_SUPPLIED_TOOLS: Tuple[ToolSpec, ...] = (
    # 6.1 Data services -> Layer 3
    ToolSpec("ahdt.data.observations", "6.1", 3,
             "Vitals, device and lab observations by LOINC code and period", ("codes",)),
    ToolSpec("ahdt.data.imaging", "6.1", 3,
             "Imaging studies (DICOMweb references) by modality and period", ("modality",)),
    ToolSpec("ahdt.data.medications", "6.1", 3, "Medication history and adherence data"),
    ToolSpec("ahdt.data.genome", "6.1", 3, "Pharmacogenomic variants", ("genes",)),
    ToolSpec("ahdt.data.graph_query", "6.1", 3,
             "GraphRAG question over the personal health knowledge graph", ("question",)),
    # 6.2 AI/ML/Simulation services -> Layer 4
    ToolSpec("ahdt.model.state", "6.2", 4, "Current state estimate of one of the 17 DTs", ("dt",),
             cacheable=False),
    ToolSpec("ahdt.model.forecast", "6.2", 4, "Forecast of a DT variable with uncertainty",
             ("dt", "variable", "horizon_h")),
    ToolSpec("ahdt.model.simulate", "6.2", 4,
             "What-if simulation of a scenario (e.g. a dose) on forked model instances",
             ("dt", "scenario"), cacheable=False, forces_fork=True),
    # 6.3 XAI services -> Layer 5
    ToolSpec("ahdt.xai.explain", "6.3", 5, "Explanation of an AHDT model output", ("output_id",)),
    # 6.4 Cognitive services
    ToolSpec("ahdt.cognitive.converse", "6.4", None,
             "Natural-language interaction in the patient's language", ("utterance", "language"),
             cacheable=False),
)

# Tools added by the ATRA build (design 03, section 3.6.2)
_ATRA_TOOLS: Tuple[ToolSpec, ...] = (
    ToolSpec("ahdt.data.timeseries", "6.1", 3,
             "One series by code and period, optionally downsampled", ("code", "period")),
    ToolSpec("ahdt.data.documents", "6.1", 3,
             "Search of notes, reports and discharge summaries", ("query",)),
    ToolSpec("ahdt.data.knowledge", "6.1", 3,
             "Allow-listed SPARQL or Cypher query with parameters", ("query_id", "params")),
    ToolSpec("ahdt.data.cohort_extract", "6.1", 3,
             "De-identified cohort rows or aggregates under k-anonymity or differential privacy",
             ("cohort_def", "fields", "privacy"), cacheable=False),
    ToolSpec("ahdt.model.facet", "6.2", 4, "Role-specific view of a shared organ instance",
             ("anatomy", "facet"), cacheable=False),
    ToolSpec("ahdt.model.cosimulate", "6.2", 4,
             "Co-simulation of several twins on forked instances",
             ("scenario", "dts", "horizon_h", "step_s"), cacheable=False, forces_fork=True),
    ToolSpec("ahdt.model.calibrate", "6.2", 4, "Re-calibration of one model instance",
             ("dt", "model_id"), cacheable=False),
    ToolSpec("ahdt.xai.causal_graph", "6.3", 5,
             "Cross-model causal explanation graph of an output", ("output_id",)),
    ToolSpec("ahdt.cognitive.perceive", "6.4", None,
             "Findings from speech, image, signal or text", ("modality",), cacheable=False),
    ToolSpec("ahdt.cognitive.reason", "6.4", None,
             "Ontology, causal, probabilistic or temporal reasoning", ("kind", "query"),
             cacheable=False),
    ToolSpec("ahdt.cognitive.request_data", "6.4", None,
             "Request for missing data from the person, a device or a clinician",
             ("what", "from"), cacheable=False),
)

AHDT_TOOLS: Tuple[ToolSpec, ...] = _SUPPLIED_TOOLS + _ATRA_TOOLS


class Role(str, enum.Enum):
    MEDICAL_OFFICER = "medical_officer"
    RADIOLOGIST = "radiologist"
    PHARMACIST = "pharmacist"
    NURSE = "nurse"
    LAB_SCIENTIST = "lab_scientist"
    PATIENT = "patient"
    PROXY = "proxy"
    COMMUNITY_HEALTH_WORKER = "community_health_worker"
    THERAPIST = "therapist"
    CARER = "carer"
    CLINICAL_SAFETY_OFFICER = "clinical_safety_officer"
    ADMINISTRATOR = "administrator"
    RESEARCHER = "researcher"
    PUBLIC_HEALTH_OFFICIAL = "public_health_official"
    PERSON = "person"


_ALL = frozenset(t.name for t in _SUPPLIED_TOOLS)
DEFAULT_ROLE_TOOLS: Dict[Role, FrozenSet[str]] = {
    Role.MEDICAL_OFFICER: _ALL,
    Role.RADIOLOGIST: frozenset({"ahdt.data.imaging", "ahdt.data.observations", "ahdt.data.graph_query",
                                 "ahdt.model.state", "ahdt.xai.explain", "ahdt.cognitive.converse"}),
    Role.PHARMACIST: frozenset({"ahdt.data.observations", "ahdt.data.medications", "ahdt.data.genome",
                                "ahdt.model.state", "ahdt.model.simulate", "ahdt.xai.explain",
                                "ahdt.cognitive.converse"}),
    Role.NURSE: frozenset({"ahdt.data.observations", "ahdt.data.medications", "ahdt.model.state",
                           "ahdt.model.forecast", "ahdt.xai.explain", "ahdt.cognitive.converse"}),
    Role.LAB_SCIENTIST: frozenset({"ahdt.data.observations", "ahdt.cognitive.converse"}),
    Role.PATIENT: frozenset({"ahdt.data.observations", "ahdt.data.medications", "ahdt.model.forecast",
                             "ahdt.xai.explain", "ahdt.cognitive.converse"}),
}
DEFAULT_ROLE_TOOLS[Role.PROXY] = DEFAULT_ROLE_TOOLS[Role.PATIENT]


@dataclass(frozen=True)
class CallContext:
    """Who is asking, for whom, and why. APDT agents act with the delegating human's role."""
    hdt_id: str                        # pseudonymous id of the patient's AHDT
    actor_role: Role
    actor_id: str
    purpose: str = "care"
    episode_id: Optional[str] = None
    agent: Optional[str] = None        # name of the 7.1/7.2 agent acting on the actor's behalf


class GatewayDenied(PermissionError):
    pass


@dataclass
class PatientConsent:
    """Patient's consent for APDT access to their AHDT.

    purposes: permitted purposes of use (e.g. {"care"}).
    refused_tools: tools the patient has explicitly withheld (e.g. {"ahdt.data.genome"}).
    """
    purposes: set = field(default_factory=lambda: {"care"})
    refused_tools: set = field(default_factory=set)


# ---------------------------------------------------------------------------
# 2. Backends: how the gateway reaches AHDT Layer 6
# ---------------------------------------------------------------------------

class AHDTBackend(abc.ABC):
    @abc.abstractmethod
    async def invoke(self, tool: str, args: Mapping[str, Any], ctx: CallContext) -> Dict[str, Any]:
        """Return the AHDT response. Responses may carry '_meta' with versions for provenance."""


Handler = Callable[[Mapping[str, Any], CallContext], Awaitable[Dict[str, Any]]]


class InMemoryAHDTBackend(AHDTBackend):
    """Test and simulation backend: register a coroutine per tool name."""

    def __init__(self) -> None:
        self.handlers: Dict[str, Handler] = {}
        self.calls: List[Tuple[str, Dict[str, Any]]] = []
        self.fail_next = 0

    def register(self, tool: str, handler: Handler) -> None:
        self.handlers[tool] = handler

    async def invoke(self, tool: str, args: Mapping[str, Any], ctx: CallContext) -> Dict[str, Any]:
        self.calls.append((tool, dict(args)))
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ConnectionError("simulated AHDT outage")
        if tool not in self.handlers:
            raise LookupError(f"AHDT has no handler for {tool}")
        return await self.handlers[tool](args, ctx)


def _context_headers(ctx: CallContext, token: str, tenant_id: Optional[str]) -> Dict[str, str]:
    """CallContext as the X-* headers of design 03, section 3.6."""
    headers = {"Authorization": f"Bearer {token}", "X-Actor-Role": ctx.actor_role.value,
               "X-Actor-Id": ctx.actor_id, "X-Purpose-Of-Use": ctx.purpose}
    for name, value in (("X-Episode-Id", ctx.episode_id), ("X-Agent", ctx.agent),
                        ("X-Tenant-Id", tenant_id)):
        if value:
            headers[name] = value
    return headers


class MCPBackend(AHDTBackend):
    """Reaches AHDT Layer 6 services published as MCP servers (streamable HTTP).

    server_urls maps a sublayer ("6.1".."6.4") to its MCP endpoint. Requires the MCP
    Python SDK 2.3 (pip install mcp). The CallContext travels in the same X-* headers
    as for RESTBackend. A tool error with status 403 raises AHDTRefused; network
    failures raise ConnectionError so the gateway retries and then degrades.
    """

    def __init__(self, server_urls: Mapping[str, str], token_provider: Callable[[], str], *,
                 tenant_id: Optional[str] = None):
        self.server_urls = dict(server_urls)
        self.token_provider = token_provider
        self.tenant_id = tenant_id
        self._sublayer = {t.name: t.sublayer for t in AHDT_TOOLS}

    async def invoke(self, tool: str, args: Mapping[str, Any], ctx: CallContext) -> Dict[str, Any]:
        from mcp import ClientSession  # lazy import
        from mcp.client.streamable_http import streamable_http_client
        from mcp.shared._httpx_utils import create_mcp_http_client
        url = self.server_urls[self._sublayer[tool]]
        client = create_mcp_http_client(
            headers=_context_headers(ctx, self.token_provider(), self.tenant_id))
        try:
            async with client, streamable_http_client(url, http_client=client) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.call_tool(tool, {**args, "hdt_id": ctx.hdt_id})
        except Exception as exc:
            if _is_transport_failure(exc):
                raise ConnectionError(f"AHDT unreachable: {exc}") from exc
            raise
        data = result.structured_content
        if result.is_error:
            error = (data or {}).get("error", {}) if isinstance(data, dict) else {}
            detail = error.get("detail") or " ".join(getattr(c, "text", "") for c in result.content)
            status = int(error.get("status", 500))
            if status == 403:
                raise AHDTRefused(detail or "denied by the AHDT")
            if status >= 500:
                raise ConnectionError(f"AHDT error {status}: {detail}")
            raise ValueError(f"{tool}: {detail}")
        if isinstance(data, dict):
            return dict(data)
        return {"content": [getattr(c, "text", str(c)) for c in result.content]}


def _is_transport_failure(exc: BaseException) -> bool:
    """True when exc (or any exception inside an ExceptionGroup) is a network failure."""
    import httpx2
    if isinstance(exc, BaseExceptionGroup):
        return any(_is_transport_failure(e) for e in exc.exceptions)
    return isinstance(exc, (httpx2.TransportError, OSError))


class AHDTRefused(RuntimeError):
    """The AHDT refused a call that passed the gateway's own checks.

    Not an OSError, so the gateway does not retry it or report it as an outage.
    """


class RESTBackend(AHDTBackend):
    """Reaches AHDT Layer 6 tools over REST: POST {base_url}/v1/tools/{tool}.

    The CallContext travels in X-* headers (design 03, section 3.6). A 403 from the AHDT
    raises AHDTRefused; 5xx and network errors raise ConnectionError so the gateway
    retries and then degrades.
    """

    def __init__(self, base_url: str, token_provider: Callable[[], str], *,
                 tenant_id: Optional[str] = None, client: Any = None):
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.tenant_id = tenant_id
        self._client = client

    def _headers(self, ctx: CallContext) -> Dict[str, str]:
        return _context_headers(ctx, self.token_provider(), self.tenant_id)

    async def invoke(self, tool: str, args: Mapping[str, Any], ctx: CallContext) -> Dict[str, Any]:
        import httpx  # lazy import
        client = self._client or httpx.AsyncClient(timeout=30.0)
        try:
            resp = await client.post(f"{self.base_url}/v1/tools/{tool}",
                                     json={**args, "hdt_id": ctx.hdt_id},
                                     headers=self._headers(ctx))
        except httpx.TransportError as exc:
            raise ConnectionError(f"AHDT unreachable: {exc}") from exc
        finally:
            if self._client is None:
                await client.aclose()
        if resp.status_code == 403:
            raise AHDTRefused(resp.json().get("detail", "denied by the AHDT"))
        if resp.status_code >= 500:
            raise ConnectionError(f"AHDT error {resp.status_code}")
        resp.raise_for_status()
        return dict(resp.json())


# ---------------------------------------------------------------------------
# 3. The gateway
# ---------------------------------------------------------------------------

@dataclass
class ToolResult:
    tool: str
    sublayer: str
    reaches_layer: Optional[int]
    data: Dict[str, Any]
    provenance: Dict[str, Any]
    cached: bool = False
    degraded: bool = False
    error: Optional[str] = None


class AHDTServiceGateway:
    """Single client through which the APDT reaches AHDT Layers 3, 4 and 5 via Layer 6."""

    def __init__(self, backend: AHDTBackend, consents: Mapping[str, PatientConsent], *,
                 role_tools: Optional[Mapping[Role, FrozenSet[str]]] = None,
                 tools: Tuple[ToolSpec, ...] = AHDT_TOOLS, cache_ttl_s: float = 300.0,
                 timeout_s: float = 10.0, max_retries: int = 2, backoff_s: float = 0.05):
        self.backend = backend
        self.consents = dict(consents)
        self.role_tools = dict(role_tools or DEFAULT_ROLE_TOOLS)
        self.tools = {t.name: t for t in tools}
        self.cache_ttl_s, self.timeout_s = cache_ttl_s, timeout_s
        self.max_retries, self.backoff_s = max_retries, backoff_s
        self._cache: Dict[str, Tuple[float, Dict[str, Any], Dict[str, Any]]] = {}
        self.audit: List[Dict[str, Any]] = []

    # ----- discovery ------------------------------------------------------
    def catalogue(self, role: Optional[Role] = None) -> List[Dict[str, Any]]:
        """Tool descriptors visible to a role, for registration with APDT agents."""
        allowed = self.role_tools.get(role, frozenset(self.tools)) if role else frozenset(self.tools)
        return [t.descriptor() for n, t in self.tools.items() if n in allowed]

    # ----- invocation -----------------------------------------------------
    async def call(self, tool: str, args: Optional[Mapping[str, Any]] = None, *,
                   ctx: CallContext) -> ToolResult:
        spec = self.tools.get(tool)
        if spec is None:
            raise KeyError(f"unknown AHDT tool {tool}")
        args = dict(args or {})
        self._authorise(spec, ctx)
        missing = [a for a in spec.required_args if a not in args]
        if missing:
            raise ValueError(f"{tool}: missing arguments {missing}")
        if spec.forces_fork:
            if args.get("fork") is False:
                self._deny(spec, ctx, "simulation on live AHDT model state is not permitted")
            args["fork"] = True

        key = f"{ctx.hdt_id}|{tool}|{json.dumps(args, sort_keys=True, default=str)}"
        if spec.cacheable and key in self._cache:
            t0, data, prov = self._cache[key]
            if time.monotonic() - t0 < self.cache_ttl_s:
                self._log(spec, ctx, "cache_hit")
                return ToolResult(tool, spec.sublayer, spec.reaches_layer, data, prov, cached=True)

        delay, last_exc = self.backoff_s, None
        for attempt in range(self.max_retries + 1):
            try:
                data = await asyncio.wait_for(self.backend.invoke(tool, args, ctx), self.timeout_s)
                break
            except (ConnectionError, asyncio.TimeoutError, OSError) as exc:
                last_exc = exc
                if attempt < self.max_retries:
                    await asyncio.sleep(delay)
                    delay *= 2
        else:
            reason = str(last_exc) or (f"no answer within {self.timeout_s:g} s"
                                       if isinstance(last_exc, asyncio.TimeoutError)
                                       else type(last_exc).__name__)
            self._log(spec, ctx, "degraded", error=reason)
            return ToolResult(tool, spec.sublayer, spec.reaches_layer, {}, self._prov(spec, ctx, {}),
                              degraded=True, error=f"AHDT evidence unavailable: {reason}")

        meta = data.pop("_meta", {}) if isinstance(data, dict) else {}
        prov = self._prov(spec, ctx, meta)
        if spec.cacheable:
            self._cache[key] = (time.monotonic(), data, prov)
        self._log(spec, ctx, "ok", call_id=prov["call_id"])
        return ToolResult(tool, spec.sublayer, spec.reaches_layer, data, prov)

    # convenience wrappers used by APDT agents
    async def observations(self, codes: List[str], *, ctx: CallContext, **kw: Any) -> ToolResult:
        return await self.call("ahdt.data.observations", {"codes": codes, **kw}, ctx=ctx)

    async def simulate(self, dt: DTKind, scenario: Mapping[str, Any], *, ctx: CallContext) -> ToolResult:
        return await self.call("ahdt.model.simulate", {"dt": dt.value, "scenario": dict(scenario)}, ctx=ctx)

    async def explain(self, output_id: str, *, ctx: CallContext, audience: str = "clinician") -> ToolResult:
        return await self.call("ahdt.xai.explain", {"output_id": output_id, "audience": audience}, ctx=ctx)

    def invalidate(self, hdt_id: str) -> None:
        """Drop cached AHDT views for a patient, e.g. after an AHDT event connector fires."""
        for k in [k for k in self._cache if k.startswith(f"{hdt_id}|")]:
            del self._cache[k]

    # ----- internals ------------------------------------------------------
    def _authorise(self, spec: ToolSpec, ctx: CallContext) -> None:
        if spec.name not in self.role_tools.get(ctx.actor_role, frozenset()):
            self._deny(spec, ctx, f"role {ctx.actor_role.value} may not use {spec.name}")
        consent = self.consents.get(ctx.hdt_id)
        if consent is None:
            self._deny(spec, ctx, "no APDT consent on record for this patient")
        if ctx.purpose not in consent.purposes:
            self._deny(spec, ctx, f"purpose '{ctx.purpose}' not consented")
        if spec.name in consent.refused_tools:
            self._deny(spec, ctx, f"patient has withheld {spec.name}")

    def _deny(self, spec: ToolSpec, ctx: CallContext, reason: str) -> None:
        self._log(spec, ctx, "denied", error=reason)
        raise GatewayDenied(reason)

    def _prov(self, spec: ToolSpec, ctx: CallContext, meta: Mapping[str, Any]) -> Dict[str, Any]:
        return {"call_id": uuid.uuid4().hex, "ahdt_service": spec.sublayer,
                "ahdt_layer": spec.reaches_layer, "called_at": time.time(),
                "actor_role": ctx.actor_role.value, "agent": ctx.agent, "purpose": ctx.purpose,
                "episode_id": ctx.episode_id, **dict(meta)}

    def _log(self, spec: ToolSpec, ctx: CallContext, outcome: str, **extra: Any) -> None:
        self.audit.append({"t": time.time(), "tool": spec.name, "hdt_id": ctx.hdt_id,
                           "actor_role": ctx.actor_role.value, "actor_id": ctx.actor_id,
                           "agent": ctx.agent, "purpose": ctx.purpose, "outcome": outcome, **extra})


# ---------------------------------------------------------------------------
# 4. Layer 6.5 connectors between APDT and AHDT
# ---------------------------------------------------------------------------

CLINICIAN_ROLES = frozenset({Role.MEDICAL_OFFICER.value, Role.RADIOLOGIST.value, Role.PHARMACIST.value,
                             Role.NURSE.value, Role.LAB_SCIENTIST.value})


class ClinicalFindingWriteBackConnector(Connector):
    """APDT -> AHDT Whole-Body DT: clinician-signed findings, diagnoses, prescriptions.

    Keeps the AHDT the complete record of the person. Unsigned or agent-only content
    is refused before it leaves the APDT.
    """

    SOURCE_KIND = DTKind.PATIENT
    TARGET_KIND = DTKind.WHOLE_BODY
    MODE = SyncMode.PUSH
    DIRECTION = Direction.UNIDIRECTIONAL
    OUT_CONTRACT = DataContract("clinical_finding", "1.0", {
        "resource_type": FieldSpec("str"),     # Condition | Observation | MedicationRequest | ...
        "code": FieldSpec("str"),
        "system": FieldSpec("str"),            # SNOMED CT, ICD-11, LOINC, RxNorm, ATC URI
        "display": FieldSpec("str"),
        "status": FieldSpec("str"),
        "author_role": FieldSpec("str"),
        "recorded_at": FieldSpec("str"),
        "value": FieldSpec("float", required=False),
        "unit": FieldSpec("str", required=False),
        "episode_id": FieldSpec("str", required=False),
    })

    def map_outbound(self, s: Mapping[str, Any]) -> Dict[str, Any]:
        if not s.get("signed_by"):
            raise ValueError("unsigned findings cannot be written back to the AHDT")
        if s.get("author_role") not in CLINICIAN_ROLES:
            raise ValueError("only clinician-authored findings are written back")
        coding = s["code"]["coding"][0]
        out = {"resource_type": s["resourceType"], "code": coding["code"],
               "system": coding["system"], "display": coding.get("display", ""),
               "status": s.get("status", "final"), "author_role": s["author_role"],
               "recorded_at": s["recorded_at"]}
        if "valueQuantity" in s:
            out["value"] = float(s["valueQuantity"]["value"])
            out["unit"] = s["valueQuantity"]["unit"]
        if s.get("episode_id"):
            out["episode_id"] = s["episode_id"]
        return out


class DeteriorationEventConnector(Connector):
    """AHDT Whole-Body DT -> APDT: early-warning events for the care orchestrator."""

    SOURCE_KIND = DTKind.WHOLE_BODY
    TARGET_KIND = DTKind.PATIENT
    MODE = SyncMode.PUSH
    DIRECTION = Direction.UNIDIRECTIONAL
    OUT_CONTRACT = DataContract("deterioration_event", "1.0", {
        "news2": FieldSpec("int", "1", min=0, max=20),
        "risk": FieldSpec("float", "1", min=0, max=1),
        "horizon_h": FieldSpec("float", "h", min=0, max=72),
        "drivers": FieldSpec("list"),
        "source_output_id": FieldSpec("str"),   # pass to ahdt.xai.explain for the explanation
    })

    def map_outbound(self, s: Mapping[str, Any]) -> Dict[str, Any]:
        return {"news2": int(s["news2"]), "risk": round(float(s["risk"]), 3),
                "horizon_h": float(s["horizon_h"]), "drivers": list(s["drivers"]),
                "source_output_id": s["output_id"]}


# ---------------------------------------------------------------------------
# 5. Demo
# ---------------------------------------------------------------------------

async def _demo() -> None:
    from atra.connectors import ConsentPolicy, InMemoryTransport, TwinEndpoint

    hdt = "hdt-7f3a91"
    backend = InMemoryAHDTBackend()

    async def observations(a, c):
        return {"series": {"8310-5": [38.9, 39.2]}, "_meta": {"ahdt_version": "3.1.0"}}

    async def simulate(a, c):
        return {"trajectory": "creatinine stable at 88 umol/L over 72 h", "fork_id": "f-01",
                "_meta": {"model": "renal-nephron v1.4", "forked": a["fork"]}}

    async def explain(a, c):
        return {"top_drivers": ["temperature trend", "heart rate"], "_meta": {"explainer": "shap 0.46"}}

    for n, h in [("ahdt.data.observations", observations), ("ahdt.model.simulate", simulate),
                 ("ahdt.xai.explain", explain)]:
        backend.register(n, h)

    gw = AHDTServiceGateway(backend, {hdt: PatientConsent({"care"}, {"ahdt.data.genome"})})
    mo = CallContext(hdt, Role.MEDICAL_OFFICER, "mo-112", episode_id="ep-2026-0931",
                     agent="differential-diagnosis-agent")

    print("Tools a pharmacist sees:", [t["name"] for t in gw.catalogue(Role.PHARMACIST)])
    r = await gw.observations(["8310-5"], ctx=mo)
    print("6.1 -> Layer 3:", r.data, r.provenance["ahdt_version"])
    r = await gw.simulate(DTKind.RENAL_URINARY, {"drug": "artemether-lumefantrine", "dose": "standard"}, ctx=mo)
    print("6.2 -> Layer 4:", r.data, "forked:", r.provenance["forked"])
    r = await gw.explain("fcst-551", ctx=mo)
    print("6.3 -> Layer 5:", r.data)
    try:
        await gw.call("ahdt.data.genome", {"genes": ["CYP2B6"]}, ctx=mo)
    except GatewayDenied as e:
        print("Denied:", e)

    bus = InMemoryTransport()
    consent = ConsentPolicy({(DTKind.PATIENT, DTKind.WHOLE_BODY): {"care"},
                             (DTKind.WHOLE_BODY, DTKind.PATIENT): {"care"}})

    async def into_ahdt(m):
        print("  [AHDT Whole-Body DT] received", m.payload["display"], m.payload["status"])

    wb = ClinicalFindingWriteBackConnector(TwinEndpoint(hdt, DTKind.PATIENT),
                                           TwinEndpoint(hdt, DTKind.WHOLE_BODY), bus,
                                           policies=[consent], on_deliver_to_target=into_ahdt)
    await wb.start()
    await wb.publish({"resourceType": "Condition", "status": "confirmed", "signed_by": "mo-112",
                      "author_role": "medical_officer", "recorded_at": "2026-09-30T10:12:00+01:00",
                      "episode_id": "ep-2026-0931",
                      "code": {"coding": [{"system": "http://snomed.info/sct", "code": "61462000",
                                           "display": "Malaria"}]}})


if __name__ == "__main__":
    asyncio.run(_demo())
