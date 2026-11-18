"""The ESP32 firmware payloads (firmware/esp32/test/fixtures, checked byte for byte by the native
tests) decode at the edge with the expected codes and units."""

from datetime import UTC, datetime

import pytest

from atra.config import ROOT
from edge.devices.decode import streams
from edge.devices.gateway import DeviceGateway
from edge.devices.transport.mqtt import Publish, encode_publish

FIXTURES = ROOT / "firmware" / "esp32" / "test" / "fixtures"
NOON = datetime(2026, 10, 10, 12, tzinfo=UTC)
HDT = "hdt-0123456789ab"


def decoded(device_class):
    return streams.decode(device_class, (FIXTURES / f"{device_class}.json").read_bytes())


def test_ecg_patch():
    [r] = decoded("ecg_patch")
    assert r.time == NOON and r.unit == "mV" and r.value["period_ms"] == 4.0
    assert r.value["array"] == pytest.approx([0.0, 52 / 1365, 1365 / 1365, -58 / 1365])


def test_imu():
    [r] = decoded("imu")
    assert r.code.code == "cadence" and r.unit == "/min" and r.value == 0


def test_dht22():
    temp, humidity = decoded("environmental")
    assert (temp.code.code, temp.value, temp.unit) == ("ambient_temp", -10.1, "Cel")
    assert (humidity.code.code, humidity.value, humidity.unit) == ("humidity", 65.2, "%")


def test_pulse_oximeter():
    spo2, pulse = decoded("pulse_oximeter")
    assert (spo2.loinc, spo2.value, spo2.unit, spo2.time) == ("59408-5", 97, "%", NOON)
    assert (pulse.loinc, pulse.value, pulse.unit) == ("8867-4", 72, "/min")


class Events:
    def __init__(self):
        self.published = []

    async def publish(self, event):
        self.published.append(event)


async def test_board_topics_reach_the_gateway():
    events = Events()
    gateway = DeviceGateway(events, None, twin_of=lambda _: "board", clock=lambda: NOON)
    gateway.register("esp32-board-1", HDT, "esp32")
    for cls in ("ecg_patch", "imu", "environmental", "pulse_oximeter"):
        topic = f"dev/{HDT}/esp32-board-1/{cls}"
        gateway.transports.mqtt.publish(encode_publish(Publish(
            topic, (FIXTURES / f"{cls}.json").read_bytes())))
    assert not gateway.dead_letters
    assert (await gateway.flush()).observations == 6
    [event] = events.published
    assert event.event_type == "ingest.board" and event.hdt_id == HDT
