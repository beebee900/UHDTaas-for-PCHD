import json

import pytest

from atra.clock import HLCStamp
from atra.connection import DeadLetterMixin, ProvenanceStampMixin, dlq_topic
from atra.connector_contracts import RANGE_GUARD, connector_purposes
from atra.connectors import (
    CardiovascularRespiratoryConnector,
    ConsentPolicy,
    DTKind,
    IndividualToPopulationConnector,
    InMemoryTransport,
    PolicyDenied,
    RangeGuardPolicy,
    TwinEndpoint,
)
from atra.contracts import ATRA_ROLE_TOOLS
from atra.policy import OPAPolicy, PolicyClient, SyncPolicyClient, run_opa_tests
from atra.provenance import ProvenanceStore

HDT = "hdt-0123456789ab"


def test_rego_unit_tests_pass():
    result = run_opa_tests()
    assert result.returncode == 0, result.stdout + result.stderr


def test_policy_data_matches_python_tables():
    from atra.policy import POLICY_DIR

    data = json.loads((POLICY_DIR / "data.json").read_text())["atra"]
    assert data["role_tools"] == {r.value: sorted(t) for r, t in ATRA_ROLE_TOOLS.items()}
    assert data["connector_purposes"] == connector_purposes()
    assert data["range_guard"] == {k: list(v) for k, v in RANGE_GUARD.items()}


async def test_tool_decisions_from_opa(opa):
    client = PolicyClient(opa.url)
    base = {"tool": "ahdt.data.genome", "role": "pharmacist", "purpose": "care",
            "hdt_id": HDT, "claims": {}, "args": {},
            "consent": {"purposes": ["care"], "refused_tools": []}}
    assert (await client.decide("ahdt.tools", base)).allow
    refused = await client.decide("ahdt.tools", {**base, "consent": {
        "purposes": ["care"], "refused_tools": ["ahdt.data.genome"]}})
    assert not refused.allow and "withheld" in refused.reason


async def test_policy_fails_closed():
    d = await PolicyClient("http://127.0.0.1:9").decide("ahdt.tools", {})
    assert not d.allow and "unavailable" in d.reason


class CV(DeadLetterMixin, ProvenanceStampMixin, CardiovascularRespiratoryConnector):
    pass


class ToPopulation(DeadLetterMixin, ProvenanceStampMixin, IndividualToPopulationConnector):
    pass


CV_STATE = {"heart_rate_bpm": 72, "stroke_volume_ml": 70, "sbp_mmhg": 120, "dbp_mmhg": 80}


async def test_stamps_hlc_and_prov_id_and_opa_allows(opa):
    bus, delivered = InMemoryTransport(), []

    async def deliver(m):
        delivered.append(m)

    store = ProvenanceStore("ahdt")
    c = CV(TwinEndpoint(HDT, DTKind.CARDIOVASCULAR), TwinEndpoint(HDT, DTKind.RESPIRATORY), bus,
           policies=[OPAPolicy(SyncPolicyClient(opa.url))], on_deliver_to_target=deliver,
           provenance_store=store)
    await c.start()
    msg = await c.publish(CV_STATE)
    assert HLCStamp.parse(msg.provenance["hlc"]).node.startswith("cardiovascular-")
    assert msg.provenance["prov_id"].startswith("atra:msg-")
    assert delivered and delivered[0].provenance["prov_id"] == msg.provenance["prov_id"]
    assert '"atra:kind": "transfer"' in store.serialize()


async def test_refused_message_goes_to_dead_letter_topic(opa):
    bus, dlq = InMemoryTransport(), []

    async def capture(raw):
        dlq.append(json.loads(raw))

    consent = ConsentPolicy({(DTKind.WHOLE_BODY, DTKind.POPULATION): {"care"}})
    c = ToPopulation(TwinEndpoint(HDT, DTKind.WHOLE_BODY),
                     TwinEndpoint("cohort", DTKind.POPULATION), bus,
                     policies=[consent, OPAPolicy(SyncPolicyClient(opa.url))], purpose="care")
    await bus.subscribe(dlq_topic(c.topic("out")), capture)
    await c.start()
    state = {"age_years": 34, "sex": "female", "address": {"state": "Lagos"},
             "condition_codes": ["61462000"]}
    with pytest.raises(PolicyDenied):
        await c.publish(state)
    assert c.metrics["dead_lettered"] == 1
    assert len(dlq) == 1
    assert "not allowed on cohort_contribution" in dlq[0]["reason"]


async def test_range_guard_refusal_is_dead_lettered():
    bus = InMemoryTransport()
    c = CV(TwinEndpoint(HDT, DTKind.CARDIOVASCULAR), TwinEndpoint(HDT, DTKind.RESPIRATORY), bus,
           policies=[RangeGuardPolicy({"heart_rate": (20, 200)})])
    await c.start()
    with pytest.raises(PolicyDenied):
        await c.publish({**CV_STATE, "heart_rate_bpm": 230})
    assert c.dead_letters[0]["direction"] == "out"
