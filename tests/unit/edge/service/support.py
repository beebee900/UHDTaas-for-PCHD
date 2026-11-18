"""Shared constants and device frames for the edge service tests."""

import json
from datetime import UTC, datetime

from atra.personas import BY_KEY
from edge.devices.transport.mqtt import Publish, encode_publish

HDT = BY_KEY["ao"].hdt_id
START = datetime(2026, 10, 1, 8, tzinfo=UTC)


def oximeter_frame(broker, device_id, t, spo2, pulse, *, packet_id=1, dup=False):
    body = json.dumps({"time": t.isoformat(), "spo2_pct": spo2, "pulse_rate": pulse}).encode()
    broker.publish(encode_publish(Publish(f"dev/{HDT}/{device_id}/pulse_oximeter", body, qos=1,
                                          packet_id=packet_id, dup=dup)))
