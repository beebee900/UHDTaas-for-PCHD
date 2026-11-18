"""MQTT 3.1.1 PUBLISH packets and topic filters, and an in-process broker for p0.

Packet layout from the OASIS MQTT Version 3.1.1 standard (29 October 2014):
- section 2.2.3: Remaining Length is a variable byte integer of up to four bytes, seven data
  bits per byte with bit 7 as the continuation flag
- section 3.3.1: fixed header byte 1 is packet type 3 in the high nibble, then DUP (bit 3),
  QoS (bits 2 and 1) and RETAIN (bit 0)
- section 3.3.2: the variable header is the Topic Name as a length-prefixed UTF-8 string,
  then a 2-byte Packet Identifier only when QoS is 1 or 2
- section 4.7: topic filters with the `+` (one level) and `#` (all remaining levels) wildcards
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

PUBLISH = 3
MAX_REMAINING = 268_435_455


class MqttError(ValueError):
    pass


@dataclass(frozen=True)
class Publish:
    topic: str
    payload: bytes
    qos: int = 0
    packet_id: int | None = None
    retain: bool = False
    dup: bool = False


def _remaining(n: int) -> bytes:
    if not 0 <= n <= MAX_REMAINING:
        raise MqttError(f"remaining length {n} is out of range")
    out = bytearray()
    while True:
        byte, n = n % 128, n // 128
        out.append(byte | 0x80 if n else byte)
        if not n:
            return bytes(out)


def encode_publish(p: Publish) -> bytes:
    if p.qos not in (0, 1, 2):
        raise MqttError(f"QoS {p.qos} is not 0, 1 or 2")
    if any(c in p.topic for c in "+#") or not p.topic:
        raise MqttError("a topic name is non-empty and has no wildcards")
    topic = p.topic.encode("utf-8")
    body = len(topic).to_bytes(2, "big") + topic
    if p.qos:
        if p.packet_id is None or not 0 < p.packet_id < 65536:
            raise MqttError("QoS 1 and 2 need a packet identifier 1..65535")
        body += p.packet_id.to_bytes(2, "big")
    body += p.payload
    first = PUBLISH << 4 | p.dup << 3 | p.qos << 1 | p.retain
    return bytes([first]) + _remaining(len(body)) + body


def decode_publish(data: bytes) -> Publish:
    if not data or data[0] >> 4 != PUBLISH:
        raise MqttError("not a PUBLISH packet")
    flags = data[0] & 0x0F
    qos = flags >> 1 & 0b11
    if qos == 3:
        raise MqttError("QoS 3 is reserved")
    n, mult, pos = 0, 1, 1
    while True:
        if pos >= len(data) or pos > 4:
            raise MqttError("malformed remaining length")
        byte = data[pos]
        n += (byte & 0x7F) * mult
        mult *= 128
        pos += 1
        if not byte & 0x80:
            break
    body = data[pos:]
    if len(body) != n:
        raise MqttError(f"remaining length {n} but {len(body)} bytes follow")
    tlen = int.from_bytes(body[:2], "big")
    topic = body[2:2 + tlen].decode("utf-8")
    rest = body[2 + tlen:]
    packet_id = None
    if qos:
        packet_id, rest = int.from_bytes(rest[:2], "big"), rest[2:]
    return Publish(topic, bytes(rest), qos, packet_id, bool(flags & 1), bool(flags & 0b1000))


def topic_matches(topic_filter: str, topic: str) -> bool:
    f, t = topic_filter.split("/"), topic.split("/")
    for i, part in enumerate(f):
        if part == "#":
            return True
        if i >= len(t) or part not in ("+", t[i]):
            return False
    return len(f) == len(t)


Handler = Callable[[Publish], None]


class MqttBroker:
    """Routes encoded PUBLISH packets to subscribers whose filter matches the topic."""

    def __init__(self) -> None:
        self._subs: list[tuple[str, Handler]] = []
        self.packets: list[bytes] = []

    def subscribe(self, topic_filter: str, handler: Handler) -> None:
        self._subs.append((topic_filter, handler))

    def publish(self, packet: bytes) -> None:
        self.packets.append(packet)
        message = decode_publish(packet)
        for topic_filter, handler in self._subs:
            if topic_matches(topic_filter, message.topic):
                handler(message)
