"""Actuator commands through the edge gateway and the autonomy check (design 04, 4.1.2)."""

import itertools
import json
from datetime import UTC, datetime

import pytest

from atra.backends.memory import MemoryWorkflows
from atra.contracts import Actor, AutonomyLevel
from atra.gateway import PatientConsent
from atra.policy import PolicyClient
from atra.provenance import AuditLog
from edge.actuators import (
    ActuationService,
    AutonomyDenied,
    AutonomyTable,
    Command,
    MqttEndpoint,
    UnknownActuator,
    actuators,
    catalogue,
    resolve,
)
from edge.devices.gateway import DeviceGateway
from edge.devices.transport import Transports
from edge.devices.transport.mqtt import Publish, decode_publish, encode_publish

HDT = "hdt-0123456789ab"
OTHER = "hdt-ba9876543210"
AGENT = Actor(id="ahdt-conductor", role="service")
DOCTOR = Actor(id="dr-ade", role="medical_officer")
NURSE = Actor(id="nurse-bisi", role="nurse")
NOW = datetime(2026, 10, 10, 12, tzinfo=UTC)
IDS = itertools.count(1)


class _Sink:
    pass


class Rig:
    def __init__(self, url, *, grants=None, consent=None, timeout_s=5.0):
        self.audit = AuditLog("edge")
        self.workflows = MemoryWorkflows()
        self.consents = {HDT: consent or PatientConsent(purposes={"care"})}
        transports = Transports()
        self.service = ActuationService(
            PolicyClient(url), self.audit, self.workflows,
            mqtt=MqttEndpoint(transports.mqtt.publish), autonomy=AutonomyTable(grants),
            consent_of=self.consents.get, approval_timeout_s=timeout_s, clock=lambda: NOW)
        self.gateway = DeviceGateway(None, _Sink(), twin_of=lambda _: None,
                                     transports=transports, actuation=self.service,
                                     clock=lambda: NOW)
        for device_id, cls in (("watch-1", "smartwatch"), ("pump-1", "insulin_pump"),
                               ("lamp-1", "lighting"), ("cpap-1", "cpap")):
            self.gateway.register(device_id, HDT, cls)
        self.gateway.register("watch-9", OTHER, "smartwatch")

    def send(self, topic, params, *, agent="ahdt-conductor", purpose="care", raw=None):
        body = raw if raw is not None else json.dumps({
            "agent": agent, "actor": AGENT.model_dump(), "purpose": purpose,
            "params": params}).encode()
        self.gateway.transports.mqtt.publish(encode_publish(Publish(topic, body)))

    async def flush(self):
        return (await self.gateway.flush()).actuations

    def device_commands(self):
        return [decode_publish(p) for p in self.gateway.transports.mqtt.packets
                if decode_publish(p).topic.startswith("cmd/")]

    def denied(self):
        return self.audit.query(outcome="denied")


@pytest.fixture
def rig(opa):
    return Rig(opa.url)


def command(actuator, params, device_id=None, agent="ahdt-conductor"):
    return Command(command_id=f"c-{next(IDS)}", hdt_id=HDT,
                   actuator=actuator, agent=agent, actor=AGENT, purpose="care", params=params,
                   device_id=device_id)


def test_policy_data_is_current():
    assert catalogue.main(["--check"]) == 0


def test_topics_resolve_to_actuators():
    classes = {"watch-1": "smartwatch", "pump-1": "insulin_pump", "lamp-1": "lighting"}.get
    assert resolve(f"act/{HDT}/phone/notify", classes) == (actuators()["notify"], None)
    assert resolve(f"act/{HDT}/channels/ussd", classes)[0].name == "ussd"
    assert resolve(f"act/{HDT}/watch-1/haptic", classes) == (actuators()["haptic"], "watch-1")
    assert resolve(f"act/{HDT}/pump-1/therapy", classes)[0].name == "insulin_pump"
    assert resolve(f"act/{HDT}/home/lamp-1", classes)[0].name == "lighting"
    for topic in (f"act/{HDT}/watch-1/therapy", f"act/{HDT}/phone/sms", f"dev/{HDT}/x/y"):
        with pytest.raises(UnknownActuator):
            resolve(topic, classes)


async def test_allowed_commands_reach_the_device_and_are_audited(rig):
    rig.send(f"act/{HDT}/watch-1/haptic", {"pattern": "double", "duration_ms": 300})
    rig.send(f"act/{HDT}/home/lamp-1", {"level_pct": 30})
    rig.send(f"act/{HDT}/phone/notify", {"title": "Medicine", "body": "Time for your tablet."})
    results = await rig.flush()
    assert [r.outcome for r in results] == ["delivered"] * 3
    cmds = rig.device_commands()
    assert [c.topic for c in cmds] == [f"cmd/{HDT}/watch-1/haptic", f"cmd/{HDT}/lamp-1/lighting"]
    assert json.loads(cmds[0].payload)["pattern"] == "double" and cmds[0].qos == 1
    assert [c.actuator for c in rig.service.outbox.sent] == ["notify"]
    ok = rig.audit.query(outcome="ok")
    assert [r.action for r in ok] == ["act.haptic", "act.lighting", "act.notify"]
    assert all(r.agent == "ahdt-conductor" and r.hdt_id == HDT for r in ok)


async def test_every_refusal_is_audited_and_nothing_is_delivered(rig):
    rig.consents[HDT] = PatientConsent(purposes={"care"}, refused_tools={"ahdt.act.sms"})
    rig.send(f"act/{HDT}/watch-1/haptic", {"pattern": "buzz"})
    rig.send(f"act/{HDT}/home/lamp-1", {"level_pct": 130})
    rig.send(f"act/{HDT}/channels/sms", {"body": "Your result is ready."})
    rig.send(f"act/{HDT}/channels/voice", {"script": "Hello"}, purpose="research")
    rig.send(f"act/{HDT}/watch-9/haptic", {"pattern": "pulse"})
    rig.send(f"act/{HDT}/ghost-1/haptic", {"pattern": "pulse"})
    rig.send(f"act/{HDT}/watch-1/haptic", {}, raw=b"{not json")
    results = await rig.flush()
    assert [r.outcome for r in results] == ["refused"] * 7
    assert not rig.device_commands() and not rig.service.outbox.sent
    denied = rig.denied()
    assert len(denied) == 7 and all(r.reason for r in denied)
    reasons = [r.reason for r in denied]
    assert "pattern=buzz is not one of" in reasons[0]
    assert "level_pct=130 outside [0, 100]" in reasons[1]
    assert "the person has withheld ahdt.act.sms" in reasons[2]
    assert "purpose 'research' not consented" in reasons[3]
    assert "not registered to" in reasons[4]
    assert [r.action for r in denied[4:]] == ["act.unrouted"] * 3
    assert rig.audit.verify_chain() == 7


async def test_agent_above_its_level_gets_autonomy_denied(opa):
    rig = Rig(opa.url, grants={"ahdt-conductor": {"notification": AutonomyLevel.RECOMMEND}})
    with pytest.raises(AutonomyDenied) as err:
        await rig.service.request(command("haptic", {"pattern": "pulse"}, "watch-1"))
    assert "autonomy level recommend is below act_with_approval" in err.value.reasons[0]
    with pytest.raises(AutonomyDenied):
        await rig.service.request(command("notify", {"title": "a", "body": "b"},
                                          agent="unlisted-agent"))
    assert [r.outcome for r in rig.denied()] == ["denied", "denied"]
    assert not rig.device_commands()


async def test_person_lowers_but_never_raises(rig):
    rig.service.autonomy.lower(HDT, "notification", AutonomyLevel.INFORM)
    with pytest.raises(ValueError):
        rig.service.autonomy.lower(HDT, "notification", AutonomyLevel.ACT)
    with pytest.raises(ValueError):
        rig.service.autonomy.lower(HDT, "clinical_actuator", AutonomyLevel.ACT)
    with pytest.raises(AutonomyDenied) as err:
        await rig.service.request(command("haptic", {"pattern": "pulse"}, "watch-1"))
    assert "autonomy level inform" in err.value.reasons[0]
    assert len(rig.denied()) == 1


async def test_therapy_waits_for_clinician_approval(rig):
    rig.send(f"act/{HDT}/pump-1/therapy", {"kind": "bolus", "bolus_u": 2.0})
    [pending] = await rig.flush()
    assert pending.outcome == "awaiting_approval" and not rig.device_commands()
    assert rig.audit.query(action="act.insulin_pump.await_approval")
    await rig.service.approve(pending.run_id, approver=DOCTOR, approved=True)
    assert await rig.workflows.result(pending.run_id, timeout_s=5) == {"outcome": "delivered"}
    [cmd] = rig.device_commands()
    assert cmd.topic == f"cmd/{HDT}/pump-1/insulin_pump"
    assert json.loads(cmd.payload)["bolus_u"] == 2.0
    [done] = rig.audit.query(action="act.insulin_pump", outcome="ok")
    assert done.actor.id == DOCTOR.id
    replay = command("insulin_pump", {"kind": "bolus", "bolus_u": 2.0}, "pump-1")
    await rig.service.request(replay)
    with pytest.raises(AutonomyDenied, match="already received"):
        await rig.service.request(replay)


async def test_therapy_refusals_are_audited(opa):
    rig = Rig(opa.url, timeout_s=0.2)
    nurse = await rig.service.request(command("insulin_pump", {"kind": "bolus", "bolus_u": 1},
                                              "pump-1"))
    await rig.service.approve(nurse.run_id, approver=NURSE, approved=True)
    declined = await rig.service.request(command("cpap", {"pressure_cmh2o": 10}, "cpap-1"))
    await rig.service.approve(declined.run_id, approver=DOCTOR, approved=False)
    silent = await rig.service.request(command("cpap", {"pressure_cmh2o": 12}, "cpap-1"))
    for r in (nurse, declined, silent):
        assert (await rig.workflows.result(r.run_id, timeout_s=5))["outcome"] == "refused"
    with pytest.raises(AutonomyDenied):
        await rig.service.request(command("insulin_pump", {"kind": "bolus", "bolus_u": 40},
                                          "pump-1"))
    assert not rig.device_commands()
    reasons = " | ".join(r.reason or "" for r in rig.denied())
    assert len(rig.denied()) == 4
    for expected in ("role nurse may not approve insulin_pump",
                     "the clinician declined the command", "no clinician approval within 0.2 s",
                     "bolus_u=40 outside [0.05, 25]"):
        assert expected in reasons
