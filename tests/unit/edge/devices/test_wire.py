"""MQTT, CoAP, ChirpStack, WFDB, STOW-RS and self-report codecs against their specifications."""

import json

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from edge.devices.decode import environment, self_report, streams, wfdb
from edge.devices.gateway import stow_parts
from edge.devices.transport import coap, mqtt

# ChirpStack v4 documentation, Integrations > Events, "up - Uplink event" JSON example
# (https://www.chirpstack.io/docs/chirpstack/integrations/events.html, read 2026-10-10).
CHIRPSTACK_UP = """{
	"deduplicationId": "3ac7e3c4-4401-4b8d-9386-a5c902f9202d",
	"time": "2022-07-18T09:34:15.775023242+00:00",
	"deviceInfo": {
		"tenantId": "52f14cd4-c6f1-4fbd-8f87-4025e1d49242",
		"tenantName": "ChirpStack",
		"applicationId": "17c82e96-be03-4f38-aef3-f83d48582d97",
		"applicationName": "Test application",
		"deviceProfileId": "14855bf7-d10d-4aee-b618-ebfcb64dc7ad",
		"deviceProfileName": "Test device-profile",
		"deviceName": "Test device",
		"devEui": "0101010101010101",
		"tags": {
			"key": "value"
		}
	},
	"devAddr": "00189440",
	"dr": 1,
	"fPort": 1,
	"data": "qg==",
	"rxInfo": [{
		"gatewayId": "0016c001f153a14c",
		"uplinkId": 4217106255,
		"rssi": -36,
		"snr": 10.5,
		"context": "E3OWOQ==",
		"metadata": {
			"region_name": "eu868",
			"region_common_name": "EU868"
		}
	}],
	"txInfo": {
		"frequency": 867100000,
		"modulation": {
			"lora": {
				"bandwidth": 125000,
				"spreadingFactor": 11,
				"codeRate": "CR_4_5"
			}
		}
	}
}"""

# WFDB Applications Guide, header(5), Example 1 (MIT DB record 100).
MITDB_100 = """100 2 360 650000 0:0:0 0/0/0
100.dat 212 200 11 1024 995 -22131 0 MLII
100.dat 212 200 11 1024 1011 20052 0 V5
# 69 M 1085 1629 x1
# Aldomet, Inderal
"""


def test_mqtt_publish_matches_the_standard_example():
    packet = mqtt.encode_publish(mqtt.Publish("a/b", b"", qos=1, packet_id=10))
    assert packet == bytes([0x32, 7, 0x00, 0x03, 0x61, 0x2F, 0x62, 0x00, 0x0A])


@given(st.binary(max_size=20000), st.sampled_from([0, 1, 2]), st.booleans())
def test_mqtt_round_trip(payload, qos, retain):
    p = mqtt.Publish("dev/hdt-000000000001/x/imu", payload, qos, 7 if qos else None, retain)
    assert mqtt.decode_publish(mqtt.encode_publish(p)) == p


def test_mqtt_remaining_length_and_filters():
    assert mqtt._remaining(127) == b"\x7f" and mqtt._remaining(128) == b"\x80\x01"
    assert mqtt._remaining(268_435_455) == b"\xff\xff\xff\x7f"
    assert mqtt.topic_matches("dev/+/+/+", "dev/h/d/imu")
    assert mqtt.topic_matches("application/#", "application/a/device/b/event/up")
    assert not mqtt.topic_matches("dev/+/+", "dev/h/d/imu")
    with pytest.raises(mqtt.MqttError):
        mqtt.encode_publish(mqtt.Publish("dev/#", b""))


def test_coap_header_options_and_payload():
    m = coap.Message(coap.CON, coap.POST, 0x7D34, b"\x01",
                     (*coap.path_options("env/nb-1"),
                      (coap.CONTENT_FORMAT, coap.uint_option(coap.APPLICATION_JSON))), b"{}")
    data = coap.encode(m)
    assert data[:5] == bytes([0x41, 0x02, 0x7D, 0x34, 0x01])
    assert data[5:9] == bytes([0xB3]) + b"env"
    assert data[9:14] == bytes([0x04]) + b"nb-1"
    assert data[14:16] == bytes([0x11, 50]) and data[16:] == b"\xff{}"
    decoded = coap.decode(data)
    assert decoded == m and decoded.uri_path == "env/nb-1" and decoded.content_format == 50
    long = coap.Message(coap.NON, coap.POST, 1, options=((300, b"x" * 300),))
    assert coap.decode(coap.encode(long)) == long
    assert coap.uint_option(0) == b""
    with pytest.raises(coap.CoapError):
        coap.decode(bytes([0x81, 0x01, 0, 0]))


def test_coap_endpoint_acknowledges_confirmables():
    endpoint = coap.CoapEndpoint()
    endpoint.resource("env/x", lambda m: coap.CHANGED)
    ack = coap.decode(endpoint.send(coap.encode(coap.Message(
        coap.CON, coap.POST, 9, b"t", coap.path_options("env/x")))))
    assert (ack.type, ack.code, ack.message_id, ack.token) == (coap.ACK, coap.CHANGED, 9, b"t")
    missing = endpoint.send(coap.encode(coap.Message(coap.CON, coap.POST, 10,
                                                     options=coap.path_options("nope"))))
    assert coap.decode(missing).code == coap.NOT_FOUND


def test_chirpstack_uplink_example_and_sensor_payload():
    up = environment.uplink(json.loads(CHIRPSTACK_UP))
    assert up.dev_eui == "0101010101010101" and up.f_port == 1 and up.data == b"\xaa"
    assert up.time.isoformat() == "2022-07-18T09:34:15.775023+00:00"
    with pytest.raises(environment.SensorPayloadError):
        environment.lora_air(json.loads(CHIRPSTACK_UP))
    assert environment.decode_lora(environment.encode_lora(45.3, -1.25, 70.5)) == (
        45.3, -1.25, 70.5)


def test_wfdb_header_example_and_format16_round_trip():
    h = wfdb.parse_header(MITDB_100)
    assert (h.name, h.fs, h.n_samples, h.start) == ("100", 360.0, 650000, None)
    assert [(s.fmt, s.gain, s.adc_res, s.adc_zero, s.init, s.checksum, s.description)
            for s in h.signals] == [(212, 200.0, 11, 1024, 995, -22131, "MLII"),
                                    (212, 200.0, 11, 1024, 1011, 20052, "V5")]
    assert h.signals[0].baseline == 1024 and h.comments[1] == "Aldomet, Inderal"
    adc = np.array([[0, 10], [200, -400], [-32768, 32767]], dtype=np.int16)
    sig = tuple(wfdb.Signal("r.dat", 16, 200.0, 0, "mV", 16, 0, 0, wfdb.checksum(adc[:, i]),
                            0, d) for i, d in enumerate(("II", "V5")))
    header = wfdb.parse_header(wfdb.Header("r", 500.0, 3, sig).text())
    values = wfdb.read_format16(header, wfdb.write_format16(adc))
    assert values[1].tolist() == [1.0, -2.0]
    with pytest.raises(wfdb.WfdbError):
        wfdb.read_format16(h, b"")


def test_stow_body_parts():
    body = (b"--b1\r\nContent-Type: application/dicom\r\n\r\nDICM-1\r\n"
            b"--b1\r\nContent-Type: application/dicom\r\n\r\nDICM-2\r\n--b1--\r\n")
    ct = 'multipart/related; type="application/dicom"; boundary=b1'
    assert stow_parts(body, ct) == [b"DICM-1", b"DICM-2"]
    with pytest.raises(ValueError):
        stow_parts(body, "application/json")


def test_self_report_scoring_and_rejections():
    from datetime import UTC, datetime

    now = datetime(2026, 10, 10, tzinfo=UTC)
    answers = dict(zip("abcdefghi", "012301230", strict=True))
    assert self_report.score("phq9", answers, now).value == 12
    with pytest.raises(self_report.SelfReportError):
        self_report.score("phq9", {**answers, "a": "7"}, now)
    with pytest.raises(self_report.SelfReportError):
        self_report.score("phq9", {"a": "1"}, now)
    xml = b'<data id="gad7">' + b"".join(f"<item_{i}>1</item_{i}>".encode()
                                       for i in range(1, 8)) + b"</data>"
    r = self_report.from_odk(xml, now)
    assert (r.code.code, r.value) == ("70274-6", 7)


def test_stream_decoders_reject_malformed_payloads():
    with pytest.raises(streams.PayloadError):
        streams.decode("imu", b"not json")
    with pytest.raises(streams.PayloadError):
        streams.decode("thermostat", b"{}")
    with pytest.raises(streams.PayloadError):
        streams.decode("insulin_pump", json.dumps(
            {"time": "2026-10-10T08:00:00", "kind": "basal", "delivered_u": 1}).encode())
