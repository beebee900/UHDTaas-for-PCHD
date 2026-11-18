import httpx
import pytest
from hypothesis import HealthCheck, given
from hypothesis import settings as hsettings
from hypothesis import strategies as st

from ahdt.app import build_app
from atra.contracts import ATRA_ROLE_TOOLS, TOOL_RESPONSES, Role
from atra.gateway import (
    AHDT_TOOLS,
    AHDTRefused,
    AHDTServiceGateway,
    CallContext,
    GatewayDenied,
    MCPBackend,
    PatientConsent,
    RESTBackend,
)
from atra.personas import BY_KEY
from atra.provenance import verify_chain
from tests.contract.fixtures import CALLER, HDT, TOOL_ARGS, bound, seed


@pytest.fixture
async def ahdt(settings, backends):
    app = build_app(settings, backends=backends("ahdt"), local_llm=False)
    await seed(app)
    return app


def token(app, role, **kw):
    return app.state.backends.issuer.issue(f"user-{role}", Role(role), tenant_id="fac-a", **kw)


async def post(app, tool, body, tok):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://ahdt") as client:
        return await client.post(f"/v1/tools/{tool}", json=body,
                                 headers={"Authorization": f"Bearer {tok}"})


def test_every_tool_has_fixture_args():
    assert set(TOOL_ARGS) == {t.name for t in AHDT_TOOLS}


@pytest.mark.parametrize("tool", sorted(TOOL_ARGS))
async def test_rest_tool_returns_schema_valid_data(ahdt, tool):
    args = await bound(ahdt, tool)
    resp = await post(ahdt, tool, {"hdt_id": HDT, **args}, token(ahdt, CALLER[tool]))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    meta = body.pop("_meta")
    assert meta["ahdt_version"]
    TOOL_RESPONSES[tool].model_validate(body)


async def test_denials_and_errors_are_problem_json(ahdt):
    lab = token(ahdt, "lab_scientist")
    resp = await post(ahdt, "ahdt.model.simulate",
                      {"hdt_id": HDT, **TOOL_ARGS["ahdt.model.simulate"]}, lab)
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/problem+json")
    gh = BY_KEY["gh"].hdt_id
    mo = token(ahdt, "medical_officer")
    resp = await post(ahdt, "ahdt.data.genome", {"hdt_id": gh, "genes": ["CYP2B6"]}, mo)
    assert resp.status_code == 403 and "withheld" in resp.json()["detail"]
    resp = await post(ahdt, "ahdt.model.simulate",
                      {"hdt_id": HDT, **TOOL_ARGS["ahdt.model.simulate"], "fork": False}, mo)
    assert resp.status_code == 403
    resp = await post(ahdt, "ahdt.model.state", {"hdt_id": HDT, "dt": "liver"}, mo)
    assert resp.status_code == 422
    resp = await post(ahdt, "ahdt.model.state", {"hdt_id": HDT, "dt": "cardiovascular"}, "x")
    assert resp.status_code == 401
    person = token(ahdt, "person", hdt_id=BY_KEY["bm"].hdt_id)
    resp = await post(ahdt, "ahdt.model.state", {"hdt_id": HDT, "dt": "cardiovascular"}, person)
    assert resp.status_code == 403 and "own twin" in resp.json()["detail"]
    records = list(ahdt.state.audit)
    assert verify_chain(records) == len(records)
    assert {r.outcome for r in records} == {"denied"}


@hsettings(max_examples=40, deadline=None,
           suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(tool=st.sampled_from(sorted(TOOL_ARGS)),
       body=st.dictionaries(st.text(min_size=1, max_size=8),
                            st.one_of(st.none(), st.integers(), st.text(max_size=8),
                                      st.lists(st.integers(), max_size=3)), max_size=4))
async def test_arbitrary_bodies_never_cause_server_errors(ahdt, tool, body):
    resp = await post(ahdt, tool, {"hdt_id": HDT, **body}, token(ahdt, "medical_officer"))
    assert resp.status_code < 500, resp.text


def _gateway(backend):
    consents = {HDT: PatientConsent({"care"}, set())}
    return AHDTServiceGateway(backend, consents, role_tools=ATRA_ROLE_TOOLS, max_retries=0)


async def test_gateway_reaches_every_tool_over_rest(ahdt):
    svc = ahdt.state.backends.issuer.issue_service("apdt-svc")
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=ahdt), base_url="http://ahdt")
    gw = _gateway(RESTBackend("http://ahdt", lambda: svc, tenant_id="fac-a", client=client))
    for tool in TOOL_ARGS:
        role = Role(CALLER[tool])
        if tool not in ATRA_ROLE_TOOLS[role]:
            continue
        args = await bound(ahdt, tool)
        result = await gw.call(tool, args, ctx=CallContext(HDT, role, "mo-112", agent="test"))
        assert not result.degraded, (tool, result.error)
        TOOL_RESPONSES[tool].model_validate(result.data)
        assert result.provenance["ahdt_version"]
    await client.aclose()


async def test_gateway_reaches_every_tool_over_mcp(ahdt, live):
    svc = ahdt.state.backends.issuer.issue_service("apdt-svc")
    with live(ahdt) as server:
        urls = {s: f"{server.url}/mcp/{n}/" for s, n in
                (("6.1", "data"), ("6.2", "model"), ("6.3", "xai"), ("6.4", "cognitive"))}
        gw = _gateway(MCPBackend(urls, lambda: svc, tenant_id="fac-a"))
        for tool in TOOL_ARGS:
            role = Role(CALLER[tool])
            if tool not in ATRA_ROLE_TOOLS[role]:
                continue
            args = await bound(ahdt, tool)
            result = await gw.call(tool, args, ctx=CallContext(HDT, role, "mo-112"))
            assert not result.degraded, (tool, result.error)
            TOOL_RESPONSES[tool].model_validate(result.data)
        with pytest.raises(AHDTRefused):
            await MCPBackend(urls, lambda: svc).invoke(
                "ahdt.data.genome", {"genes": ["CYP2B6"]},
                CallContext(BY_KEY["gh"].hdt_id, Role.MEDICAL_OFFICER, "mo-112"))
    with pytest.raises(GatewayDenied):
        await gw.call("ahdt.model.calibrate", TOOL_ARGS["ahdt.model.calibrate"],
                      ctx=CallContext(HDT, Role.NURSE, "rn-1"))


async def test_mcp_outage_degrades(ahdt):
    gw = _gateway(MCPBackend({"6.2": "http://127.0.0.1:9/mcp/model/"}, lambda: "t"))
    result = await gw.call("ahdt.model.state", {"dt": "cardiovascular"},
                           ctx=CallContext(HDT, Role.MEDICAL_OFFICER, "mo-112"))
    assert result.degraded and "unavailable" in result.error


async def test_agent_cards(ahdt):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=ahdt),
                                 base_url="http://ahdt") as client:
        card = (await client.get("/a2a/ahdt-conductor/.well-known/agent-card.json")).json()
        assert {s["id"] for s in card["skills"]} == {"submit_goal", "get_status", "arbitrate"}
        message = {"messageId": "m1", "role": "ROLE_USER",
                   "parts": [{"data": {"skill": "get_goals"}}]}
        resp = await client.post("/a2a/ahdt-orchestrator-cardiovascular/",
                                 headers={"A2A-Version": "1.0"},
                                 json={"jsonrpc": "2.0", "id": 1, "method": "SendMessage",
                                       "params": {"message": message}})
        data = resp.json()["result"]["message"]["parts"][0]["data"]
        assert data["twin"] == "cardiovascular" and data["goals"]
