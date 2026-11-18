"""In-process transports for p0: an MQTT broker, a CoAP endpoint, BLE notification links and
11073-20601 manager links. Each carries the real wire bytes, so swapping in a network
transport changes the delivery, not the payloads."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from edge.devices.transport.coap import CoapEndpoint
from edge.devices.transport.mqtt import MqttBroker, Publish

Notify = Callable[[str, int, bytes, datetime | None], None]


@dataclass
class BleLink:
    """GATT notifications and indications: (device_id, characteristic UUID, value bytes).
    `at` is the receive time on the simulated clock; a radio link leaves it to the gateway."""

    _subs: list[Notify] = field(default_factory=list)
    frames: list[tuple[str, int, bytes]] = field(default_factory=list)

    def subscribe(self, handler: Notify) -> None:
        self._subs.append(handler)

    def notify(self, device_id: str, uuid: int, value: bytes,
               at: datetime | None = None) -> None:
        self.frames.append((device_id, uuid, value))
        for handler in self._subs:
            handler(device_id, uuid, value, at)


Manager = Callable[[str, bytes], bytes | None]


@dataclass
class PhdLink:
    """An 11073-20601 association: the agent sends APDU bytes and gets the manager's reply."""

    manager: Manager
    frames: list[tuple[str, bytes]] = field(default_factory=list)

    def send(self, device_id: str, apdu: bytes) -> bytes | None:
        self.frames.append(("agent", apdu))
        reply = self.manager(device_id, apdu)
        if reply is not None:
            self.frames.append(("manager", reply))
        return reply


@dataclass
class Transports:
    mqtt: MqttBroker = field(default_factory=MqttBroker)
    coap: CoapEndpoint = field(default_factory=CoapEndpoint)
    ble: BleLink = field(default_factory=BleLink)
    phd: PhdLink | None = None


__all__ = ["BleLink", "CoapEndpoint", "MqttBroker", "PhdLink", "Publish", "Transports"]
