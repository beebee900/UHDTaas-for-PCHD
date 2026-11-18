"""Actuators of design 04, 4.1.2, behind the autonomy check of design 03, 3.14.

Command topics, deliveries and AHDT levels (`actuators.yaml` holds the full table):

- `act/{hdt_id}/phone/notify`: phone notification, outbox for FCM or the in-app WebSocket,
  `act`
- `act/{hdt_id}/channels/{sms,ussd,voice}` and `act/{hdt_id}/carer/message`: outbox for the
  channels service and APDT tasks, `act`
- `act/{hdt_id}/{device_id}/haptic` and `act/{hdt_id}/home/{device_id}` (lighting,
  ventilation): `cmd/{hdt_id}/{device_id}/{actuator}`, `act`
- `act/{hdt_id}/{device_id}/therapy` (insulin pump, CPAP, rehabilitation robot):
  `cmd/{hdt_id}/{device_id}/{actuator}` after a clinician's approval, `act_with_approval`

Agents publish commands on `act/` topics. Only the edge gateway publishes on `cmd/` topics, so
a device receives a command only after the check.
"""

from edge.actuators.autonomy import AutonomyDenied, AutonomyTable
from edge.actuators.catalogue import Actuator, UnknownActuator, actuators, resolve
from edge.actuators.service import (
    ActuationResult,
    ActuationService,
    Command,
    MqttEndpoint,
    Outbox,
)

__all__ = ["ActuationResult", "ActuationService", "Actuator", "AutonomyDenied", "AutonomyTable",
           "Command", "MqttEndpoint", "Outbox", "UnknownActuator", "actuators", "resolve"]
