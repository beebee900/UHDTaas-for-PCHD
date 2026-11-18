import asyncio

import pytest

from atra.connectors import (
    CardiovascularRespiratoryConnector,
    Connector,
    ConnectorManager,
    ConnectorState,
    ConsentPolicy,
    ContractViolation,
    DataContract,
    DTKind,
    EndocrineBehaviouralConnector,
    FieldSpec,
    IndividualToPopulationConnector,
    InMemoryTransport,
    PolicyDenied,
    QoS,
    RangeGuardPolicy,
    SyncMode,
    TwinEndpoint,
)

HDT = "hdt-test"


def ep(kind, hdt=HDT):
    return TwinEndpoint(hdt, kind)


def all_care_consent():
    kinds = list(DTKind)
    return ConsentPolicy({(a, b): {"care", "public_health"} for a in kinds for b in kinds})


def run(coro):
    return asyncio.run(coro)


def cv_state(**kw):
    s = {"heart_rate_bpm": 72, "stroke_volume_ml": 70, "sbp_mmhg": 124, "dbp_mmhg": 82}
    s.update(kw)
    return s


def test_outbound_mapping_units_and_delivery():
    async def go():
        got = []
        bus = InMemoryTransport()

        async def deliver(m):
            got.append(m)

        c = CardiovascularRespiratoryConnector(ep(DTKind.CARDIOVASCULAR), ep(DTKind.RESPIRATORY),
                                               bus, policies=[all_care_consent()],
                                               on_deliver_to_target=deliver)
        await c.start()
        await c.publish(cv_state())
        assert len(got) == 1
        p = got[0].payload
        assert p["cardiac_output"] == pytest.approx(5.04)
        assert p["mean_arterial_pressure"] == pytest.approx(96.0)
        assert got[0].units["cardiac_output"] == "L/min"
        assert c.topic() == f"hdt/{HDT}/cardiovascular/to/respiratory/haemodynamics/v1"
    run(go())


def test_bidirectional_reply_and_inbound_mapping():
    async def go():
        back = []
        bus = InMemoryTransport()

        async def to_source(m):
            back.append(m)

        c = CardiovascularRespiratoryConnector(ep(DTKind.CARDIOVASCULAR), ep(DTKind.RESPIRATORY),
                                               bus, policies=[all_care_consent()],
                                               on_deliver_to_source=to_source)
        await c.start()
        await c.reply({"spo2": 96.0, "respiratory_rate": 15.0})
        assert back[0].payload["sao2_fraction"] == pytest.approx(0.96)
    run(go())


def test_contract_violation_blocks_send():
    async def go():
        bus = InMemoryTransport()
        c = CardiovascularRespiratoryConnector(ep(DTKind.CARDIOVASCULAR), ep(DTKind.RESPIRATORY), bus)
        await c.start()
        with pytest.raises(ContractViolation):
            await c.publish(cv_state(heart_rate_bpm=400))
        assert bus.published == []
    run(go())


def test_consent_denied():
    async def go():
        bus = InMemoryTransport()
        consent = ConsentPolicy({(DTKind.WHOLE_BODY, DTKind.POPULATION): {"public_health"}})
        c = IndividualToPopulationConnector(ep(DTKind.WHOLE_BODY), ep(DTKind.POPULATION, "cohort"),
                                            bus, policies=[consent], purpose="marketing")
        await c.start()
        with pytest.raises(PolicyDenied):
            await c.publish({"age_years": 30, "sex": "male", "address": {"state": "Oyo"}})
        assert c.metrics["denied"] == 1
    run(go())


def test_deidentification():
    async def go():
        got = []
        bus = InMemoryTransport()

        async def deliver(m):
            got.append(m)

        c = IndividualToPopulationConnector(ep(DTKind.WHOLE_BODY), ep(DTKind.POPULATION, "cohort"),
                                            bus, policies=[all_care_consent()], purpose="public_health",
                                            on_deliver_to_target=deliver)
        await c.start()
        await c.publish({"age_years": 47, "sex": "female",
                         "address": {"street": "x", "lga": "Yaba", "state": "Lagos"},
                         "weight_kg": 78, "height_m": 1.63})
        p = got[0].payload
        assert p["age_band"] == "45-49" and p["state"] == "Lagos"
        assert "street" not in str(p) and "Yaba" not in str(p)
    run(go())


def test_wrong_endpoint_kind_rejected():
    with pytest.raises(ValueError):
        CardiovascularRespiratoryConnector(ep(DTKind.RENAL_URINARY), ep(DTKind.RESPIRATORY),
                                           InMemoryTransport())


def test_retry_then_success():
    async def go():
        bus = InMemoryTransport()
        bus.fail_next = 2
        c = EndocrineBehaviouralConnector(ep(DTKind.ENDOCRINE), ep(DTKind.BEHAVIOURAL_COGNITIVE), bus,
                                          qos=QoS(max_retries=3, backoff_s=0.001))
        await c.start()
        await c.publish({"glucose_mmol_l": 6.1, "tir_pct": 80})
        assert c.metrics["retries"] == 2 and c.metrics["sent"] == 1
        assert c.state is ConnectorState.RUNNING
    run(go())


def test_buffer_and_flush_after_outage():
    async def go():
        got = []
        bus = InMemoryTransport()

        async def deliver(m):
            got.append(m)

        c = EndocrineBehaviouralConnector(ep(DTKind.ENDOCRINE), ep(DTKind.BEHAVIOURAL_COGNITIVE), bus,
                                          qos=QoS(max_retries=1, backoff_s=0.001),
                                          on_deliver_to_target=deliver)
        await c.start()
        bus.fail_next = 2
        await c.publish({"glucose_mmol_l": 6.1, "tir_pct": 80})
        assert c.state is ConnectorState.DEGRADED and got == []
        assert await c.flush() == 1
        assert len(got) == 1 and c.state is ConnectorState.RUNNING
    run(go())


def test_duplicate_is_ignored():
    async def go():
        got = []
        bus = InMemoryTransport()

        async def deliver(m):
            got.append(m)

        c = EndocrineBehaviouralConnector(ep(DTKind.ENDOCRINE), ep(DTKind.BEHAVIOURAL_COGNITIVE), bus,
                                          on_deliver_to_target=deliver)
        await c.start()
        await c.publish({"glucose_mmol_l": 6.1, "tir_pct": 80})
        topic, raw = bus.published[-1]
        await bus.publish(topic, raw)
        assert len(got) == 1 and c.metrics["duplicates"] == 1
    run(go())


def test_tampered_message_rejected():
    async def go():
        got = []
        bus = InMemoryTransport()

        async def deliver(m):
            got.append(m)

        c = EndocrineBehaviouralConnector(ep(DTKind.ENDOCRINE), ep(DTKind.BEHAVIOURAL_COGNITIVE), bus,
                                          on_deliver_to_target=deliver)
        await c.start()
        await c.publish({"glucose_mmol_l": 6.1, "tir_pct": 80})
        topic, raw = bus.published[-1]
        await bus.publish(topic, raw.replace(b"6.1", b"9.9").replace(b'"msg_id": "', b'"msg_id": "x'))
        assert len(got) == 1 and c.metrics["rejected"] == 1
    run(go())


class RenalHepaticQuery(Connector):
    """Request-reply specialisation defined in the test: Hepatobiliary asks Renal for eGFR."""
    SOURCE_KIND = DTKind.RENAL_URINARY
    TARGET_KIND = DTKind.HEPATOBILIARY
    MODE = SyncMode.REQUEST_REPLY
    OUT_CONTRACT = DataContract("renal_function", "2.0", {
        "egfr": FieldSpec("float", "mL/min/{1.73_m2}", min=1, max=200)})

    def map_outbound(self, s):
        return {"egfr": float(s["egfr"])}


def test_request_reply_and_custom_specialisation():
    async def go():
        bus = InMemoryTransport()

        async def renal_state():
            return {"egfr": 58.0}

        c = RenalHepaticQuery(ep(DTKind.RENAL_URINARY), ep(DTKind.HEPATOBILIARY), bus,
                              state_provider=renal_state)
        await c.start()
        msg = await c.request()
        assert msg.payload == {"egfr": 58.0} and msg.correlation_id
    run(go())


def test_range_guard_policy():
    async def go():
        bus = InMemoryTransport()
        c = EndocrineBehaviouralConnector(ep(DTKind.ENDOCRINE), ep(DTKind.BEHAVIOURAL_COGNITIVE), bus,
                                          policies=[RangeGuardPolicy({"glucose": (2.0, 30.0)})])
        await c.start()
        with pytest.raises(PolicyDenied):
            await c.publish({"glucose_mmol_l": 1.5, "tir_pct": 50})
    run(go())


def test_manager_coupling_matrix():
    bus = InMemoryTransport()
    m = ConnectorManager(HDT)
    m.register(CardiovascularRespiratoryConnector(ep(DTKind.CARDIOVASCULAR), ep(DTKind.RESPIRATORY), bus))
    m.register(EndocrineBehaviouralConnector(ep(DTKind.ENDOCRINE), ep(DTKind.BEHAVIOURAL_COGNITIVE), bus))
    cm = m.coupling_matrix()
    assert cm["cardiovascular"]["respiratory"] == ["haemodynamics"]
    assert cm["respiratory"]["cardiovascular"] == ["gas_exchange"]
    assert cm["behavioural_cognitive"]["endocrine"] == ["behaviour_summary"]
