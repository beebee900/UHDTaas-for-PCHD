"""Acceptance: a local alert fires with the cloud down (design 08 WP11; design 07, 7.7).

The AHDT cannot be reached, so the edge raises the alert itself from the kb critical-value
rules and its ONNX model, notifies the phone and sends the SMS for the channels service. The
actuator commands pass the real OPA autonomy policy."""


import pytest

from atra.backends.memory import MemoryWorkflows
from atra.gateway import PatientConsent
from atra.policy import PolicyClient
from atra.provenance import AuditLog
from edge.actuators import ActuationService, MqttEndpoint
from edge.alerts import AlertDispatcher, AlertRules
from edge.devices.transport import Transports
from edge.inference import EdgeModel, EdgeModelSpec, OnnxHost
from edge.outbox import LinkDown, Outbox
from edge.registry import DeviceCA, DeviceRegistry
from edge.runtime import EdgeRuntime
from tests.unit.edge.service.support import HDT, oximeter_frame
from tests.unit.edge.service.test_inference import DESAT, desaturation_model


class CloudDown:
    def __init__(self):
        self.calls = 0

    async def ingest(self, observations):
        self.calls += 1
        raise LinkDown("AHDT unreachable")


def edge(edge_settings, opa, clock, profile, *, consent=True):
    transports = Transports()
    consents = {HDT: PatientConsent(purposes={"care"})} if consent else {}
    actuation = ActuationService(PolicyClient(opa.url), AuditLog("edge"), MemoryWorkflows(),
                                 mqtt=MqttEndpoint(transports.mqtt.publish),
                                 consent_of=consents.get, clock=clock.now)
    models = OnnxHost([EdgeModel(EdgeModelSpec.model_validate(DESAT), desaturation_model())])
    link = CloudDown()
    rt = EdgeRuntime(edge_settings.model_copy(update={"link": profile}),
                     registry=DeviceRegistry(None, DeviceCA.generate()),
                     outbox=Outbox(None, clock=clock.now), ingestor=link, models=models,
                     rules=AlertRules(), actuation=actuation,
                     dispatcher=AlertDispatcher(actuation), transports=transports,
                     clock=clock.now)
    rt.registry.register("po-1", "pulse_oximeter", HDT)
    return rt, actuation, link


def desaturate(rt, clock):
    for i, spo2 in enumerate((95, 91, 88, 87, 89, 90)):
        oximeter_frame(rt.transports.mqtt, "po-1", clock.now(), spo2, 104, packet_id=i + 1)
        clock.advance(10)


@pytest.mark.parametrize("profile", ["offline", "wifi"])
async def test_desaturation_alerts_locally_and_by_sms_with_the_cloud_down(
        edge_settings, opa, clock, profile):
    rt, actuation, link = edge(edge_settings, opa, clock, profile)
    desaturate(rt, clock)
    result = await rt.step()

    assert not result.cloud_reachable
    assert link.calls == (0 if profile == "offline" else 1)
    assert rt.outbox.counts()["pending"] == 12
    rules = {(a.source, a.rule, a.urgency) for a in result.alerts}
    assert ("rule", "pulmonary_oedema_spo2", "emergency") in rules
    assert ("model", "desaturation", "urgent") in rules
    # The rule fires once per person within its repeat interval, not once per reading.
    sent = [d for d in result.dispatched if d.alert.rule == "pulmonary_oedema_spo2"]
    (first,) = sent
    assert first.notify.outcome == "delivered" and first.sms.outcome == "delivered"
    sms = [c for c in actuation.outbox.sent if c.actuator == "sms"]
    assert [c.params["body"] for c in sms] == [first.alert.text]
    assert first.alert.text.startswith("ATRA emergency alert: spo2 91 % at")
    # The urgent model alert reaches the phone but is not sent by SMS.
    (model_alert,) = [d for d in result.dispatched if d.alert.source == "model"]
    assert model_alert.notify.outcome == "delivered" and model_alert.sms is None
    logged = rt.dispatcher.recent()
    assert {(a["rule"], a["notified"], a["sms"]) for a in logged} == {
        ("pulmonary_oedema_spo2", "delivered", "delivered"),
        ("desaturation", "delivered", None)}

    clock.advance(60)
    oximeter_frame(rt.transports.mqtt, "po-1", clock.now(), 86, 106, packet_id=99)
    again = await rt.step()
    assert any(a.rule == "pulmonary_oedema_spo2" for a in again.alerts)
    assert not [d for d in again.dispatched if d.alert.rule == "pulmonary_oedema_spo2"]


async def test_no_sms_while_the_cloud_answers(edge_settings, opa, clock):
    rt, actuation, _ = edge(edge_settings, opa, clock, "wifi")

    class CloudUp:
        async def ingest(self, observations):
            from edge.outbox import Ack
            return Ack(len(observations), 0, 0)

    rt.forwarder.ingestor = CloudUp()
    desaturate(rt, clock)
    result = await rt.step()
    assert result.cloud_reachable and result.dispatched
    assert all(d.sms is None for d in result.dispatched)
    assert not [c for c in actuation.outbox.sent if c.actuator == "sms"]


async def test_without_consent_the_policy_refuses_and_the_refusal_is_logged(
        edge_settings, opa, clock):
    rt, actuation, _ = edge(edge_settings, opa, clock, "offline", consent=False)
    desaturate(rt, clock)
    result = await rt.step()
    assert result.dispatched
    assert all(d.notify.outcome == "refused" for d in result.dispatched)
    assert actuation.outbox.sent == []
    assert {a["notified"] for a in rt.dispatcher.recent()} == {"refused"}
