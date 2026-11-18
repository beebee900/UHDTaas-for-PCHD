import asyncio

import pytest

from atra.connectors import ConsentPolicy, DTKind, InMemoryTransport, TwinEndpoint
from atra.gateway import (
    AHDTServiceGateway,
    CallContext,
    ClinicalFindingWriteBackConnector,
    DeteriorationEventConnector,
    GatewayDenied,
    InMemoryAHDTBackend,
    PatientConsent,
    Role,
)

HDT = "hdt-p1"


def run(c):
    return asyncio.run(c)


def make_gateway(**kw):
    be = InMemoryAHDTBackend()

    async def obs(a, c):
        return {"series": {"8867-4": [88, 91]}, "_meta": {"ahdt_version": "3.1.0"}}

    async def sim(a, c):
        return {"ok": True, "_meta": {"forked": a["fork"]}}

    async def expl(a, c):
        return {"drivers": ["hr"]}

    be.register("ahdt.data.observations", obs)
    be.register("ahdt.model.simulate", sim)
    be.register("ahdt.xai.explain", expl)
    consent = kw.pop("consent", PatientConsent({"care"}, {"ahdt.data.genome"}))
    return AHDTServiceGateway(be, {HDT: consent}, backoff_s=0.001, **kw), be


def ctx(role=Role.MEDICAL_OFFICER, purpose="care"):
    return CallContext(HDT, role, "u1", purpose=purpose, agent="test-agent")


def test_layer_mapping_and_provenance():
    gw, _ = make_gateway()
    r = run(gw.observations(["8867-4"], ctx=ctx()))
    assert r.sublayer == "6.1" and r.reaches_layer == 3
    assert r.provenance["ahdt_version"] == "3.1.0" and r.provenance["agent"] == "test-agent"
    r = run(gw.explain("x", ctx=ctx()))
    assert r.sublayer == "6.3" and r.reaches_layer == 5


def test_simulation_forced_onto_fork():
    gw, be = make_gateway()
    r = run(gw.simulate(DTKind.RENAL_URINARY, {"dose": 1}, ctx=ctx()))
    assert r.reaches_layer == 4 and r.provenance["forked"] is True
    with pytest.raises(GatewayDenied):
        run(gw.call("ahdt.model.simulate", {"dt": "renal_urinary", "scenario": {}, "fork": False}, ctx=ctx()))


def test_role_policy():
    gw, _ = make_gateway()
    with pytest.raises(GatewayDenied):
        run(gw.simulate(DTKind.ENDOCRINE, {}, ctx=ctx(Role.LAB_SCIENTIST)))
    names = {t["name"] for t in gw.catalogue(Role.LAB_SCIENTIST)}
    assert "ahdt.model.simulate" not in names and "ahdt.data.observations" in names


def test_consent_purpose_and_withheld_tool():
    gw, _ = make_gateway()
    with pytest.raises(GatewayDenied):
        run(gw.observations(["x"], ctx=ctx(purpose="research")))
    with pytest.raises(GatewayDenied):
        run(gw.call("ahdt.data.genome", {"genes": ["CYP2C9"]}, ctx=ctx()))
    assert any(a["outcome"] == "denied" for a in gw.audit)


def test_missing_arguments():
    gw, _ = make_gateway()
    with pytest.raises(ValueError):
        run(gw.call("ahdt.data.observations", {}, ctx=ctx()))


def test_cache_and_invalidate():
    gw, be = make_gateway()
    run(gw.observations(["a"], ctx=ctx()))
    r = run(gw.observations(["a"], ctx=ctx()))
    assert r.cached and len(be.calls) == 1
    gw.invalidate(HDT)
    run(gw.observations(["a"], ctx=ctx()))
    assert len(be.calls) == 2


def test_degraded_when_ahdt_unreachable():
    gw, be = make_gateway(max_retries=1)
    be.fail_next = 5
    r = run(gw.observations(["a"], ctx=ctx()))
    assert r.degraded and "unavailable" in r.error


def test_retry_recovers():
    gw, be = make_gateway(max_retries=2)
    be.fail_next = 1
    r = run(gw.observations(["a"], ctx=ctx()))
    assert not r.degraded and len(be.calls) == 2


FINDING = {"resourceType": "Condition", "status": "confirmed", "signed_by": "mo-1",
           "author_role": "medical_officer", "recorded_at": "2026-09-30T10:00:00+01:00",
           "code": {"coding": [{"system": "http://snomed.info/sct", "code": "61462000",
                                "display": "Malaria"}]}}


def _consent():
    return ConsentPolicy({(DTKind.PATIENT, DTKind.WHOLE_BODY): {"care"},
                          (DTKind.WHOLE_BODY, DTKind.PATIENT): {"care"}})


def test_write_back_signed_finding():
    async def go():
        got = []
        bus = InMemoryTransport()

        async def d(m):
            got.append(m)

        c = ClinicalFindingWriteBackConnector(TwinEndpoint(HDT, DTKind.PATIENT),
                                              TwinEndpoint(HDT, DTKind.WHOLE_BODY), bus,
                                              policies=[_consent()], on_deliver_to_target=d)
        await c.start()
        await c.publish(FINDING)
        assert got[0].payload["code"] == "61462000"
        with pytest.raises(ValueError):
            await c.publish({**FINDING, "signed_by": None})
        with pytest.raises(ValueError):
            await c.publish({**FINDING, "author_role": "agent"})
    run(go())


def test_deterioration_event_to_apdt():
    async def go():
        got = []
        bus = InMemoryTransport()

        async def d(m):
            got.append(m)

        c = DeteriorationEventConnector(TwinEndpoint(HDT, DTKind.WHOLE_BODY),
                                        TwinEndpoint(HDT, DTKind.PATIENT), bus,
                                        policies=[_consent()], on_deliver_to_target=d)
        await c.start()
        await c.publish({"news2": 6, "risk": 0.4213, "horizon_h": 12, "drivers": ["rr", "spo2"],
                         "output_id": "fc-9"})
        assert got[0].payload["risk"] == 0.421 and got[0].payload["source_output_id"] == "fc-9"
    run(go())


def test_patient_kind_not_an_ahdt_member():
    assert not DTKind.PATIENT.is_ahdt_member and DTKind.WHOLE_BODY.is_ahdt_member
    assert sum(k.is_ahdt_member for k in DTKind) == 17
