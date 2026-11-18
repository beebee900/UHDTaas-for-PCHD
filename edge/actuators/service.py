"""The actuation service: every actuator command passes the autonomy check (design 04, 4.1.2).

A command arrives as JSON on its `act/` topic or through `request`:
`{command_id, agent, actor: {id, role}, purpose, params, tenant_id?, trace_id?}`.
OPA package `ahdt.actuation` decides it from the agent's granted level, the person's lowered
level, the person's consent and the actuator's parameter limits, giving one of three outcomes:

- delivered: the command goes to its endpoint at once;
- awaiting approval: a workflow waits for a clinician's `approval` signal from the AHDT
  clinical view, decides again with that approval, then delivers or refuses;
- refused: nothing is delivered and `request` raises `AutonomyDenied`.

Every outcome is written to the audit log, refusals with outcome `denied` and the policy's
reasons. A command that cannot be read or routed is refused and audited the same way.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol

from atra.backends.base import WorkflowBackend, WorkflowContext
from atra.contracts import Actor
from atra.gateway import PatientConsent
from atra.ids import new_record_id
from atra.policy import PolicyClient, PolicyDecision
from atra.provenance import AuditLog
from edge.actuators.autonomy import AutonomyDenied, AutonomyTable
from edge.actuators.catalogue import Actuator, UnknownActuator, actuators, resolve
from edge.devices.transport.mqtt import Publish, encode_publish

PACKAGE = "ahdt.actuation"
WORKFLOW = "actuation.approval"
SIGNAL = "approval"
UNROUTED = Actor(id="unknown", role="unknown")

type Outcome = Literal["delivered", "awaiting_approval", "refused"]


@dataclass(frozen=True)
class Command:
    command_id: str
    hdt_id: str
    actuator: str
    agent: str
    actor: Actor
    purpose: str
    params: dict[str, Any]
    device_id: str | None = None
    tenant_id: str | None = None
    trace_id: str | None = None

    @property
    def spec(self) -> Actuator:
        return actuators()[self.actuator]

    @property
    def topic(self) -> str:
        return self.spec.topic_for(self.hdt_id, self.device_id)

    def to_json(self) -> dict[str, Any]:
        return {"command_id": self.command_id, "hdt_id": self.hdt_id, "actuator": self.actuator,
                "agent": self.agent, "actor": self.actor.model_dump(), "purpose": self.purpose,
                "params": self.params, "device_id": self.device_id,
                "tenant_id": self.tenant_id, "trace_id": self.trace_id}

    @classmethod
    def from_json(cls, o: dict[str, Any]) -> Command:
        return cls(**{**o, "actor": Actor.model_validate(o["actor"])})


@dataclass(frozen=True)
class ActuationResult:
    command: Command | None
    outcome: Outcome
    reasons: tuple[str, ...] = ()
    run_id: str | None = None


class Endpoint(Protocol):
    def deliver(self, command: Command) -> None: ...


@dataclass
class MqttEndpoint:
    """Approved device commands on `cmd/{hdt_id}/{device_id}/{actuator}`, QoS 1."""

    publish: Callable[[bytes], None]
    _packet_id: int = 0

    def deliver(self, command: Command) -> None:
        self._packet_id = self._packet_id % 65535 + 1
        body = json.dumps({"command_id": command.command_id, **command.params}).encode()
        self.publish(encode_publish(Publish(
            f"cmd/{command.hdt_id}/{command.device_id}/{command.actuator}", body, qos=1,
            packet_id=self._packet_id)))


@dataclass
class Outbox:
    """Phone notifications, channel messages and carer messages for their delivery adapters
    (FCM or the in-app WebSocket, the channels service, APDT tasks)."""

    sent: list[Command] = field(default_factory=list)

    def deliver(self, command: Command) -> None:
        self.sent.append(command)


class ActuationService:
    def __init__(self, policy: PolicyClient, audit: AuditLog, workflows: WorkflowBackend, *,
                 mqtt: MqttEndpoint, outbox: Outbox | None = None,
                 autonomy: AutonomyTable | None = None,
                 consent_of: Callable[[str], PatientConsent | None] = lambda _: None,
                 approval_timeout_s: float = 3600.0,
                 clock: Callable[[], datetime] = lambda: datetime.now(UTC)) -> None:
        self.policy = policy
        self.audit = audit
        self.workflows = workflows
        self.mqtt = mqtt
        self.outbox = outbox or Outbox()
        self.autonomy = autonomy or AutonomyTable()
        self.consent_of = consent_of
        self.approval_timeout_s = approval_timeout_s
        self.clock = clock
        self.results: list[ActuationResult] = []
        self._queue: list[Publish] = []
        workflows.register(WORKFLOW, self._approval_workflow)

    def endpoint(self, command: Command) -> Endpoint:
        return self.mqtt if command.spec.device_classes else self.outbox

    def _input(self, command: Command, approval: dict[str, Any] | None = None) -> dict[str, Any]:
        spec = command.spec
        consent = self.consent_of(command.hdt_id)
        person = self.autonomy.person_level(command.hdt_id, spec.action_class)
        inp: dict[str, Any] = {
            "actuator": command.actuator, "purpose": command.purpose, "params": command.params,
            "granted": self.autonomy.granted(command.agent, spec.action_class).value}
        if person is not None:
            inp["person_level"] = person.value
        if consent is not None:
            inp["consent"] = {"purposes": sorted(consent.purposes),
                              "refused_tools": sorted(consent.refused_tools)}
        if approval is not None:
            inp["approval"] = {"role": approval.get("role"),
                               "approved": approval.get("approved") is True}
        return inp

    def _audit(self, command: Command | None, outcome: Literal["ok", "denied"], *,
               action: str, target: str, reason: str | None = None,
               actor: Actor | None = None) -> None:
        self.audit.append(
            actor=actor or (command.actor if command else UNROUTED),
            action=action, target=target,
            purpose=command.purpose if command else "care", outcome=outcome,
            agent=command.agent if command else None,
            hdt_id=command.hdt_id if command else None,
            tenant_id=command.tenant_id if command else None,
            trace_id=command.trace_id if command else None, reason=reason, t=self.clock())

    def _refuse(self, command: Command | None, reasons: tuple[str, ...], *, target: str,
                actor: Actor | None = None) -> ActuationResult:
        action = f"act.{command.actuator}" if command else "act.unrouted"
        self._audit(command, "denied", action=action, target=target,
                    reason="; ".join(reasons), actor=actor)
        result = ActuationResult(command, "refused", reasons)
        self.results.append(result)
        return result

    def _deliver(self, command: Command, *, actor: Actor | None = None) -> ActuationResult:
        self.endpoint(command).deliver(command)
        self._audit(command, "ok", action=f"act.{command.actuator}", target=command.topic,
                    actor=actor)
        result = ActuationResult(command, "delivered")
        self.results.append(result)
        return result

    async def _decide(self, command: Command,
                      approval: dict[str, Any] | None = None) -> PolicyDecision:
        return await self.policy.decide(PACKAGE, self._input(command, approval))

    async def request(self, command: Command) -> ActuationResult:
        """Check and carry out one command; raises `AutonomyDenied` when it is refused."""
        decision = await self._decide(command)
        if decision.raw.get("needs_approval"):
            run_id = f"act-{command.command_id}"
            if await self._exists(run_id):
                reasons = (f"command {command.command_id} was already received",)
                self._refuse(command, reasons, target=command.topic)
                raise AutonomyDenied(command.command_id, reasons)
            await self.workflows.start(WORKFLOW, {"command": command.to_json()}, run_id=run_id)
            self._audit(command, "ok", action=f"act.{command.actuator}.await_approval",
                        target=command.topic)
            result = ActuationResult(command, "awaiting_approval", run_id=run_id)
            self.results.append(result)
            return result
        if not decision.allow:
            self._refuse(command, decision.reasons or ("refused by policy",),
                         target=command.topic)
            raise AutonomyDenied(command.command_id, decision.reasons)
        return self._deliver(command)

    async def _exists(self, run_id: str) -> bool:
        try:
            await self.workflows.status(run_id)
        except KeyError:
            return False
        return True

    async def approve(self, run_id: str, *, approver: Actor, approved: bool) -> None:
        """A clinician's decision from the AHDT clinical view."""
        await self.workflows.signal(run_id, SIGNAL, {"id": approver.id, "role": approver.role,
                                                     "approved": approved})

    async def _approval_workflow(self, ctx: WorkflowContext, *, command: dict[str, Any]
                                 ) -> dict[str, Any]:
        cmd = Command.from_json(command)
        try:
            approval = await ctx.wait_signal(SIGNAL, timeout_s=self.approval_timeout_s)
        except TimeoutError:
            self._refuse(cmd, (f"no clinician approval within {self.approval_timeout_s:g} s",),
                         target=cmd.topic)
            return {"outcome": "refused"}
        approver = Actor(id=str(approval.get("id")), role=str(approval.get("role")))
        decision = await self._decide(cmd, approval)
        if not decision.allow:
            self._refuse(cmd, decision.reasons or ("refused by policy",), target=cmd.topic,
                         actor=approver)
            return {"outcome": "refused", "reasons": list(decision.reasons)}

        async def deliver() -> str:
            self._deliver(cmd, actor=approver)
            return "delivered"

        return {"outcome": await ctx.activity(deliver)}

    def on_mqtt(self, message: Publish) -> None:
        self._queue.append(message)

    def command_of(self, message: Publish,
                   device_of: Callable[[str], tuple[str, str] | None]) -> Command:
        """The command on an `act/` topic; `device_of` gives a device's (hdt_id, class)."""
        def device_class(device_id: str) -> str | None:
            found = device_of(device_id)
            return found[1] if found else None

        spec, device_id = resolve(message.topic, device_class)
        hdt_id = message.topic.split("/")[1]
        if device_id is not None:
            owner = device_of(device_id)
            if owner is None or owner[0] != hdt_id:
                raise UnknownActuator(f"device {device_id} is not registered to {hdt_id}")
        o = json.loads(message.payload)
        return Command(
            command_id=str(o.get("command_id") or new_record_id()), hdt_id=hdt_id,
            actuator=spec.name, agent=str(o["agent"]), actor=Actor.model_validate(o["actor"]),
            purpose=str(o.get("purpose", "care")), params=dict(o.get("params", {})),
            device_id=device_id, tenant_id=o.get("tenant_id"), trace_id=o.get("trace_id"))

    async def process(self, device_of: Callable[[str], tuple[str, str] | None]
                      ) -> list[ActuationResult]:
        """Handle the commands received on `act/` topics since the last call."""
        queue, self._queue = self._queue, []
        out = []
        for message in queue:
            try:
                command = self.command_of(message, device_of)
            except (UnknownActuator, ValueError, KeyError, TypeError) as exc:
                out.append(self._refuse(None, (f"{type(exc).__name__}: {exc}",),
                                        target=message.topic))
                continue
            try:
                out.append(await self.request(command))
            except AutonomyDenied:
                out.append(self.results[-1])
        return out
