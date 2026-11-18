"""Environmental sensor simulators: a CoAP (NB-IoT class) air sensor and a LoRaWAN air sensor
whose uplinks reach the edge as ChirpStack v4 `up` events (formats in
`edge.devices.decode.environment`)."""

from __future__ import annotations

import base64
import json
import uuid
from dataclasses import dataclass

from edge.devices.decode.environment import LORA_FPORT, encode_lora
from edge.devices.sim.base import Simulator, seed_of
from edge.devices.transport import coap
from edge.devices.transport.mqtt import MqttBroker, Publish, encode_publish

APPLICATION_ID = "00000000-0000-4000-8000-00000000a1f0"


@dataclass
class CoapAirSensor(Simulator):
    def run(self, endpoint: coap.CoapEndpoint) -> list[int]:
        """Confirmable POSTs; returns the response code of each ACK."""
        codes = []
        for n, t in enumerate(self.schedule("pm25")):
            body = json.dumps({"time": self.stream.when(t).isoformat(),
                               "pm25_ugm3": round(self.measure("pm25", t), 1),
                               "temperature_c": round(self.measure("ambient_temp", t), 2),
                               "humidity_pct": round(self.measure("humidity", t), 1)})
            request = coap.Message(
                coap.CON, coap.POST, n % 65536, token=n.to_bytes(2, "big"),
                options=(*coap.path_options(f"env/{self.device_id}"),
                         (coap.CONTENT_FORMAT, coap.uint_option(coap.APPLICATION_JSON))),
                payload=body.encode())
            ack = endpoint.send(coap.encode(request))
            if ack is not None:
                codes.append(coap.decode(ack).code)
        return codes


@dataclass
class LoraAirSensor(Simulator):
    """`device_id` is the 16-hex-digit DevEUI."""

    def run(self, broker: MqttBroker) -> None:
        for n, t in enumerate(self.schedule("pm25")):
            data = encode_lora(self.measure("pm25", t), self.measure("ambient_temp", t),
                               self.measure("humidity", t))
            event = {
                "deduplicationId": str(uuid.UUID(int=seed_of(self.device_id, str(n)) << 64)),
                "time": self.stream.when(t).isoformat(),
                "deviceInfo": {"tenantId": APPLICATION_ID, "tenantName": "ATRA",
                               "applicationId": APPLICATION_ID,
                               "applicationName": "environment",
                               "deviceProfileId": APPLICATION_ID,
                               "deviceProfileName": "air-sensor",
                               "deviceName": f"air-{self.device_id[-4:]}",
                               "devEui": self.device_id},
                "devAddr": self.device_id[-8:], "dr": 5, "fPort": LORA_FPORT,
                "data": base64.b64encode(data).decode(),
            }
            topic = f"application/{APPLICATION_ID}/device/{self.device_id}/event/up"
            broker.publish(encode_publish(Publish(topic, json.dumps(event).encode())))
