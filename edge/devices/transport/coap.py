"""CoAP messages (RFC 7252) and an in-process endpoint for NB-IoT-class sensors in p0.

The codec covers section 3 (4-byte header, token, options as delta/length TLVs with the 13 and
14 extensions, 0xFF payload marker) and section 3.2 uint option values. Option numbers and
codes come from the registries of section 12: Uri-Path 11, Content-Format 12, POST 0.02,
Changed 2.04, Not Found 4.04, Unsupported Content-Format 4.15, application/json 50.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

VERSION = 1
CON, NON, ACK, RST = 0, 1, 2, 3
URI_PATH = 11
CONTENT_FORMAT = 12
APPLICATION_JSON = 50
POST = 0x02
CHANGED = 0x44
NOT_FOUND = 0x84
UNSUPPORTED_CONTENT_FORMAT = 0x8F
PAYLOAD_MARKER = 0xFF


class CoapError(ValueError):
    pass


@dataclass(frozen=True)
class Message:
    type: int
    code: int
    message_id: int
    token: bytes = b""
    options: tuple[tuple[int, bytes], ...] = field(default_factory=tuple)
    payload: bytes = b""

    def option(self, number: int) -> list[bytes]:
        return [v for n, v in self.options if n == number]

    @property
    def uri_path(self) -> str:
        return "/".join(v.decode("utf-8") for v in self.option(URI_PATH))

    @property
    def content_format(self) -> int | None:
        values = self.option(CONTENT_FORMAT)
        return int.from_bytes(values[0], "big") if values else None


def uint_option(value: int) -> bytes:
    """Section 3.2: the shortest big-endian form; zero is the empty value."""
    return value.to_bytes((value.bit_length() + 7) // 8, "big")


def path_options(path: str) -> tuple[tuple[int, bytes], ...]:
    return tuple((URI_PATH, seg.encode("utf-8")) for seg in path.strip("/").split("/") if seg)


def _ext(n: int) -> tuple[int, bytes]:
    if n < 13:
        return n, b""
    if n < 269:
        return 13, bytes([n - 13])
    return 14, (n - 269).to_bytes(2, "big")


def encode(m: Message) -> bytes:
    if len(m.token) > 8:
        raise CoapError("a token is at most 8 bytes")
    out = bytearray([VERSION << 6 | m.type << 4 | len(m.token), m.code])
    out += m.message_id.to_bytes(2, "big") + m.token
    last = 0
    for number, value in sorted(m.options, key=lambda o: o[0]):
        delta, dext = _ext(number - last)
        length, lext = _ext(len(value))
        out += bytes([delta << 4 | length]) + dext + lext + value
        last = number
    if m.payload:
        out += bytes([PAYLOAD_MARKER]) + m.payload
    return bytes(out)


def _read_ext(nibble: int, data: bytes, pos: int) -> tuple[int, int]:
    if nibble == 13:
        return data[pos] + 13, pos + 1
    if nibble == 14:
        return int.from_bytes(data[pos:pos + 2], "big") + 269, pos + 2
    if nibble == 15:
        raise CoapError("reserved option nibble 15")
    return nibble, pos


def decode(data: bytes) -> Message:
    if len(data) < 4:
        raise CoapError("shorter than the 4-byte header")
    if data[0] >> 6 != VERSION:
        raise CoapError(f"unknown CoAP version {data[0] >> 6}")
    tkl = data[0] & 0x0F
    if tkl > 8:
        raise CoapError("token length 9-15 is a format error")
    token, pos = data[4:4 + tkl], 4 + tkl
    options: list[tuple[int, bytes]] = []
    number = 0
    payload = b""
    while pos < len(data):
        if data[pos] == PAYLOAD_MARKER:
            payload = data[pos + 1:]
            if not payload:
                raise CoapError("payload marker followed by an empty payload")
            break
        head = data[pos]
        delta, pos = _read_ext(head >> 4, data, pos + 1)
        length, pos = _read_ext(head & 0x0F, data, pos)
        number += delta
        options.append((number, data[pos:pos + length]))
        pos += length
    return Message((data[0] >> 4) & 0b11, data[1], int.from_bytes(data[2:4], "big"), token,
                   tuple(options), payload)


Resource = Callable[[Message], int]


class CoapEndpoint:
    """A server that answers each datagram; confirmable requests get a piggybacked ACK."""

    def __init__(self) -> None:
        self._resources: dict[str, Resource] = {}
        self.datagrams: list[bytes] = []

    def resource(self, path: str, handler: Resource) -> None:
        self._resources[path.strip("/")] = handler

    def send(self, datagram: bytes) -> bytes | None:
        self.datagrams.append(datagram)
        request = decode(datagram)
        handler = self._resources.get(request.uri_path)
        code = NOT_FOUND if handler is None else handler(request)
        if request.type != CON:
            return None
        return encode(Message(ACK, code, request.message_id, request.token))
