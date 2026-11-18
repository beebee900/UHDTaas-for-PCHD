"""Acceptance of WP17: per connector a mapping, contract-violation, consent-denial and DLQ test."""

import json

import pytest

from atra.connection import DeadLetterRecord, dlq_topic
from atra.connectors import ContractViolation, Message, PolicyDenied, SyncMode
from atra.gateway import PatientConsent

from .cases import ALL_PAIRS, CASES, REPLIES, pair_id
from .conftest import HDT

PAIRS = pytest.mark.parametrize("pair", ALL_PAIRS, ids=pair_id)


def same(actual, expected):
    """Equal payloads, with floats compared approximately."""
    assert set(actual) == set(expected)
    for key, want in expected.items():
        got = actual[key]
        if isinstance(want, float) and not isinstance(want, bool):
            assert got == pytest.approx(want), key
        else:
            assert got == want, key


def dlq_records(rig, topic):
    return [json.loads(d) for t, d in rig.transport.published if t == dlq_topic(topic)]


def received(inbox, connector):
    return [d for d in inbox.delivered if d.name == connector.name]


@PAIRS
async def test_mapping(rig, pair):
    name, source, target = pair
    case = CASES[name]
    c, inbox = await rig.connector(*pair)
    if c.MODE is SyncMode.REQUEST_REPLY:
        async def answer(query):
            assert query == {"for": target.value}
            return case.valid

        c.query_provider = answer
        msg = await c.request({"for": target.value})
    else:
        msg = await c.publish(case.valid, sim_time=60.0)
    same(msg.payload, case.expected)
    assert msg.units == c.OUT_CONTRACT.units()
    assert msg.provenance["connector"] == type(c).__name__
    assert {"hlc", "prov_id", "content_hash"} <= set(msg.provenance)
    [delivery] = received(inbox, c)
    assert delivery.receiver is target and delivery.source is source
    same(inbox.payloads(target)[name], case.expected)
    assert [e.event_type for e in rig.bus.published] == ["connector.delivered"]


@pytest.mark.parametrize("name", sorted(REPLIES))
async def test_reply_mapping(rig, name):
    pair = next(p for p in ALL_PAIRS if p[0] == name)
    _, source, target = pair
    case = REPLIES[name]
    c, inbox = await rig.connector(*pair)
    msg = await c.reply_from(case.valid)
    same(msg.payload, case.expected)
    [delivery] = received(inbox, c)
    assert delivery.receiver is source and delivery.source is target
    with pytest.raises(ContractViolation):
        await c.reply_from(case.invalid)
    assert dlq_records(rig, c.topic("in"))[0]["direction"] == "out"


@PAIRS
async def test_contract_violation(rig, pair):
    name, _, _ = pair
    c, inbox = await rig.connector(*pair)
    with pytest.raises(ContractViolation):
        await c.publish(CASES[name].invalid)
    assert received(inbox, c) == []
    assert c.metrics["sent"] == 0
    [record] = dlq_records(rig, c.topic("out"))
    assert record["direction"] == "out" and record["connector"] == c.name


@PAIRS
async def test_consent_denial(rig, pair):
    name, _, _ = pair
    c, inbox = await rig.connector(*pair)
    others = {"care", "self_management", "public_health"} - {c.purpose}
    rig.consents.set(HDT, PatientConsent(others, set()))
    with pytest.raises(PolicyDenied, match="consent"):
        await c.publish(CASES[name].valid)
    assert received(inbox, c) == []
    assert c.metrics["denied"] == 1
    assert "consent" in dlq_records(rig, c.topic("out"))[0]["reason"]


@PAIRS
async def test_dead_letter_queue(rig, pair):
    c, inbox = await rig.connector(*pair)
    forged = Message(source=c.source.uri, target=c.target.uri,
                     contract=f"{c.OUT_CONTRACT.name}/v{c.OUT_CONTRACT.version}",
                     payload={"bogus": 1}, units={}, purpose=c.purpose)
    await rig.transport.publish(c.topic("out"), forged.to_bytes())
    assert received(inbox, c) == []
    [record] = dlq_records(rig, c.topic("out"))
    DeadLetterRecord.model_validate(record)
    assert record["direction"] == "in" and "unexpected fields" in record["reason"]
    assert record["message"]["msg_id"] == forged.msg_id
    [event] = [e for e in rig.bus.published if e.event_type == "connector.dead_lettered"]
    assert event.hdt_id == HDT
    assert event.payload == {"connector": c.name, "message_id": forged.msg_id,
                             "topic": c.topic("out"), "reason": record["reason"]}
