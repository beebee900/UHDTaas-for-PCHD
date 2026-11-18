"""Environmental sensors: CoAP JSON (NB-IoT class) and LoRaWAN uplinks through ChirpStack.

The CoAP sensor POSTs `{time, pm25_ugm3, temperature_c, humidity_pct}` as application/json
(Content-Format 50) to `env/{device_id}`.

The LoRaWAN sensor sends a 5-byte application payload on FPort 1, big-endian:
PM2.5 uint16 in 0.1 ug/m3, temperature int16 in 0.01 Cel, relative humidity uint8 in 0.5 %.
ChirpStack v4 forwards it as the `up` event of its MQTT integration on topic
`application/{application_id}/device/{dev_eui}/event/up`; the JSON follows the UplinkEvent
example of the ChirpStack v4 documentation (Integrations, Events), with the payload
base64-encoded in `data`.
"""

from __future__ import annotations

import base64
import json
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from edge.devices.decode.observations import CodedReading, field_reading

LORA_FPORT = 1
LORA_FORMAT = ">HhB"
UPLINK_TOPIC = "application/+/device/+/event/up"


class SensorPayloadError(ValueError):
    pass


@dataclass(frozen=True)
class Air:
    time: datetime
    pm25: float
    temperature: float
    humidity: float

    def readings(self) -> list[CodedReading]:
        return [*field_reading("pm25", self.pm25, "ug/m3", self.time),
                *field_reading("ambient_temp", self.temperature, "Cel", self.time),
                *field_reading("humidity", self.humidity, "%", self.time)]


def coap_payload(payload: bytes) -> Air:
    o = json.loads(payload)
    return Air(datetime.fromisoformat(o["time"]), float(o["pm25_ugm3"]),
               float(o["temperature_c"]), float(o["humidity_pct"]))


def encode_lora(pm25: float, temperature: float, humidity: float) -> bytes:
    return struct.pack(LORA_FORMAT, round(pm25 * 10), round(temperature * 100),
                       round(humidity * 2))


def decode_lora(data: bytes) -> tuple[float, float, float]:
    if len(data) != struct.calcsize(LORA_FORMAT):
        raise SensorPayloadError(f"the sensor payload is 5 bytes, got {len(data)}")
    pm, t, h = struct.unpack(LORA_FORMAT, data)
    return pm / 10, t / 100, h / 2


@dataclass(frozen=True)
class Uplink:
    dev_eui: str
    time: datetime
    f_port: int
    data: bytes


def uplink(event: Mapping[str, Any]) -> Uplink:
    """The fields of a ChirpStack `up` event this edge uses; nanosecond times are cut to
    microseconds."""
    raw = str(event["time"])
    match = re.fullmatch(r"(.*?\.)(\d+)(.*)", raw)
    if match:
        raw = f"{match[1]}{match[2][:6]}{match[3]}"
    return Uplink(str(event["deviceInfo"]["devEui"]), datetime.fromisoformat(raw),
                  int(event.get("fPort", 0)), base64.b64decode(event.get("data", "")))


def lora_air(event: Mapping[str, Any]) -> Air:
    up = uplink(event)
    if up.f_port != LORA_FPORT:
        raise SensorPayloadError(f"no sensor payload on FPort {up.f_port}")
    return Air(up.time, *decode_lora(up.data))
