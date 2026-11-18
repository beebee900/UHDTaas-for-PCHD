"""IEEE 11073-20601 APDUs in MDER (big-endian) encoding: association, release, abort, and the
confirmed event reports that carry configuration and scan reports.

The standard is not public. The structures follow the Antidote stack (commit dbb27422):
`src/asn1/phd_types.h` for the types and choice values, and
`src/communication/parser/encoder_ASN1.c` for field order and length fields. The codec is
tested against Antidote's copies of the 20601 Annex H example APDUs
(`tests/resources/apdu`). Data APDUs other than event reports and their results (GET, SET,
ACTION, errors, rejects) are not implemented and raise `UnsupportedApdu`.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field

# APDU choices.
AARQ = 0xE200
AARE = 0xE300
RLRQ = 0xE400
RLRE = 0xE500
ABRT = 0xE600
PRST = 0xE700

# DATA APDU message choices.
ROIV_CMIP_EVENT_REPORT = 0x0100
ROIV_CMIP_CONFIRMED_EVENT_REPORT = 0x0101
RORS_CMIP_CONFIRMED_EVENT_REPORT = 0x0201

ASSOC_VERSION1 = 0x80000000
PROTOCOL_VERSION1 = 0x80000000
NOM_VERSION1 = 0x80000000
MDER = 0x8000
XER = 0x4000
PER = 0x2000
SYS_TYPE_MANAGER = 0x80000000
SYS_TYPE_AGENT = 0x00800000
DATA_PROTO_ID_20601 = 20601
MANAGER_CONFIG_RESPONSE = 0x0000
EXTENDED_CONFIG_START = 0x4000

# Associate-result values.
ACCEPTED = 0
REJECTED_PERMANENT = 1
REJECTED_TRANSIENT = 2
ACCEPTED_UNKNOWN_CONFIG = 3
REJECTED_NO_COMMON_PROTOCOL = 4
REJECTED_NO_COMMON_PARAMETER = 5
REJECTED_UNKNOWN = 6
REJECTED_UNAUTHORIZED = 7
REJECTED_UNSUPPORTED_ASSOC_VERSION = 8

# ConfigResult values.
ACCEPTED_CONFIG = 0x0000
UNSUPPORTED_CONFIG = 0x0001
STANDARD_CONFIG_UNKNOWN = 0x0002

DATA_REQ_ID_AGENT_INITIATED = 0xF000


class DecodeError(ValueError):
    """An APDU is truncated or its length fields disagree with its content."""


class UnsupportedApdu(DecodeError):
    """A well-formed APDU of a kind this codec does not implement."""


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data = bytes(data)
        self.pos = 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise DecodeError(f"APDU ends at octet {len(self.data)}, needs {self.pos + n}")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        value: int = struct.unpack(">H", self.take(2))[0]
        return value

    def u32(self) -> int:
        value: int = struct.unpack(">I", self.take(4))[0]
        return value

    def octets(self) -> bytes:
        """An octet string or `Any`: a 16-bit length, then the content."""
        return self.take(self.u16())

    def sub(self) -> _Reader:
        """A reader over the next length-prefixed content."""
        return _Reader(self.octets())

    def done(self) -> None:
        if self.pos != len(self.data):
            raise DecodeError(f"{len(self.data) - self.pos} octets left over")


def _u16(v: int) -> bytes:
    return struct.pack(">H", v)


def _u32(v: int) -> bytes:
    return struct.pack(">I", v)


def _octets(content: bytes) -> bytes:
    return _u16(len(content)) + content


def _list(items: list[bytes]) -> bytes:
    """A SEQUENCE OF: count, total length, then the items."""
    body = b"".join(items)
    return _u16(len(items)) + _u16(len(body)) + body


def _read_list(r: _Reader) -> tuple[int, _Reader]:
    """The item count and a reader over the items of a SEQUENCE OF."""
    count = r.u16()
    return count, r.sub()


@dataclass(frozen=True)
class Attribute:
    """AVA-Type: an attribute id (term code, partition 1) and its encoded value."""

    attribute_id: int
    value: bytes

    def encode(self) -> bytes:
        return _u16(self.attribute_id) + _octets(self.value)

    @classmethod
    def read(cls, r: _Reader) -> Attribute:
        return cls(r.u16(), r.octets())


def _attributes(r: _Reader) -> tuple[Attribute, ...]:
    count, body = _read_list(r)
    items = tuple(Attribute.read(body) for _ in range(count))
    body.done()
    return items


@dataclass(frozen=True)
class AssociationInformation:
    """PhdAssociationInformation, the data-proto-info of the 20601 protocol."""

    system_id: bytes
    dev_config_id: int
    system_type: int = SYS_TYPE_AGENT
    protocol_version: int = PROTOCOL_VERSION1
    encoding_rules: int = MDER
    nomenclature_version: int = NOM_VERSION1
    functional_units: int = 0
    data_req_mode_flags: int = 0
    data_req_init_agent_count: int = 0
    data_req_init_manager_count: int = 0
    options: tuple[Attribute, ...] = ()

    def encode(self) -> bytes:
        return (_u32(self.protocol_version) + _u16(self.encoding_rules)
                + _u32(self.nomenclature_version) + _u32(self.functional_units)
                + _u32(self.system_type) + _octets(self.system_id) + _u16(self.dev_config_id)
                + _u16(self.data_req_mode_flags)
                + bytes([self.data_req_init_agent_count, self.data_req_init_manager_count])
                + _list([a.encode() for a in self.options]))

    @classmethod
    def decode(cls, data: bytes) -> AssociationInformation:
        r = _Reader(data)
        protocol, encoding, nomenclature = r.u32(), r.u16(), r.u32()
        functional, system_type = r.u32(), r.u32()
        system_id, config = r.octets(), r.u16()
        flags, agent_count, manager_count = r.u16(), r.u8(), r.u8()
        options = _attributes(r)
        r.done()
        return cls(system_id, config, system_type, protocol, encoding, nomenclature, functional,
                   flags, agent_count, manager_count, options)


@dataclass(frozen=True)
class DataProto:
    data_proto_id: int
    info: bytes

    def encode(self) -> bytes:
        return _u16(self.data_proto_id) + _octets(self.info)

    @classmethod
    def read(cls, r: _Reader) -> DataProto:
        return cls(r.u16(), r.octets())

    @property
    def phd(self) -> AssociationInformation | None:
        if self.data_proto_id != DATA_PROTO_ID_20601:
            return None
        return AssociationInformation.decode(self.info)


@dataclass(frozen=True)
class AssociationRequest:
    data_protos: tuple[DataProto, ...]
    assoc_version: int = ASSOC_VERSION1

    @property
    def phd(self) -> AssociationInformation | None:
        """The 20601 association information, if the agent offers that protocol."""
        for proto in self.data_protos:
            if proto.data_proto_id == DATA_PROTO_ID_20601:
                return proto.phd
        return None


@dataclass(frozen=True)
class AssociationResponse:
    result: int
    selected: DataProto


@dataclass(frozen=True)
class ReleaseRequest:
    reason: int = 0


@dataclass(frozen=True)
class ReleaseResponse:
    reason: int = 0


@dataclass(frozen=True)
class Abort:
    reason: int = 0


@dataclass(frozen=True)
class EventReport:
    """roiv-cmip-(confirmed-)event-report with an EventReportArgumentSimple."""

    invoke_id: int
    event_type: int
    event_info: bytes
    obj_handle: int = 0
    event_time: int = 0xFFFFFFFF
    confirmed: bool = True


@dataclass(frozen=True)
class EventReportResult:
    """rors-cmip-confirmed-event-report with an EventReportResultSimple."""

    invoke_id: int
    event_type: int
    reply_info: bytes = b""
    obj_handle: int = 0
    current_time: int = 0


type Apdu = (AssociationRequest | AssociationResponse | ReleaseRequest | ReleaseResponse | Abort
             | EventReport | EventReportResult)


def _data_apdu(invoke_id: int, choice: int, body: bytes) -> bytes:
    return _u16(invoke_id) + _u16(choice) + _octets(body)


def encode(apdu: Apdu) -> bytes:
    """The APDU as bytes, with every length field computed."""
    match apdu:
        case AssociationRequest():
            choice = AARQ
            body = _u32(apdu.assoc_version) + _list([p.encode() for p in apdu.data_protos])
        case AssociationResponse():
            choice, body = AARE, _u16(apdu.result) + apdu.selected.encode()
        case ReleaseRequest():
            choice, body = RLRQ, _u16(apdu.reason)
        case ReleaseResponse():
            choice, body = RLRE, _u16(apdu.reason)
        case Abort():
            choice, body = ABRT, _u16(apdu.reason)
        case EventReport():
            message = (ROIV_CMIP_CONFIRMED_EVENT_REPORT if apdu.confirmed
                       else ROIV_CMIP_EVENT_REPORT)
            arg = (_u16(apdu.obj_handle) + _u32(apdu.event_time) + _u16(apdu.event_type)
                   + _octets(apdu.event_info))
            choice, body = PRST, _octets(_data_apdu(apdu.invoke_id, message, arg))
        case EventReportResult():
            res = (_u16(apdu.obj_handle) + _u32(apdu.current_time) + _u16(apdu.event_type)
                   + _octets(apdu.reply_info))
            choice = PRST
            body = _octets(_data_apdu(apdu.invoke_id, RORS_CMIP_CONFIRMED_EVENT_REPORT, res))
    return _u16(choice) + _octets(body)


def decode(data: bytes) -> Apdu:
    outer = _Reader(data)
    choice = outer.u16()
    r = outer.sub()
    outer.done()
    result: Apdu
    if choice == AARQ:
        version = r.u32()
        count, protos = _read_list(r)
        result = AssociationRequest(tuple(DataProto.read(protos) for _ in range(count)), version)
        protos.done()
    elif choice == AARE:
        result = AssociationResponse(r.u16(), DataProto.read(r))
    elif choice == RLRQ:
        result = ReleaseRequest(r.u16())
    elif choice == RLRE:
        result = ReleaseResponse(r.u16())
    elif choice == ABRT:
        result = Abort(r.u16())
    elif choice == PRST:
        result = _decode_data(r.sub())
    else:
        raise UnsupportedApdu(f"APDU choice 0x{choice:04X}")
    r.done()
    return result


def _decode_data(r: _Reader) -> Apdu:
    invoke_id, message = r.u16(), r.u16()
    body = r.sub()
    r.done()
    result: Apdu
    if message in (ROIV_CMIP_EVENT_REPORT, ROIV_CMIP_CONFIRMED_EVENT_REPORT):
        handle, time, event_type = body.u16(), body.u32(), body.u16()
        result = EventReport(invoke_id, event_type, body.octets(), handle, time,
                             message == ROIV_CMIP_CONFIRMED_EVENT_REPORT)
    elif message == RORS_CMIP_CONFIRMED_EVENT_REPORT:
        handle, time, event_type = body.u16(), body.u32(), body.u16()
        result = EventReportResult(invoke_id, event_type, body.octets(), handle, time)
    else:
        raise UnsupportedApdu(f"DATA APDU message 0x{message:04X}")
    body.done()
    return result


# Event-info structures ---------------------------------------------------------------------

@dataclass(frozen=True)
class ObservationScanFixed:
    obj_handle: int
    data: bytes


@dataclass(frozen=True)
class ScanReportFixed:
    """ScanReportInfoFixed, the event-info of MDC_NOTI_SCAN_REPORT_FIXED."""

    observations: tuple[ObservationScanFixed, ...]
    scan_report_no: int = 0
    data_req_id: int = DATA_REQ_ID_AGENT_INITIATED

    def encode(self) -> bytes:
        return (_u16(self.data_req_id) + _u16(self.scan_report_no)
                + _list([_u16(o.obj_handle) + _octets(o.data) for o in self.observations]))

    @classmethod
    def decode(cls, data: bytes) -> ScanReportFixed:
        r = _Reader(data)
        req, number = r.u16(), r.u16()
        count, items = _read_list(r)
        obs = tuple(ObservationScanFixed(items.u16(), items.octets()) for _ in range(count))
        items.done()
        r.done()
        return cls(obs, number, req)


@dataclass(frozen=True)
class ConfigObject:
    obj_class: int
    obj_handle: int
    attributes: tuple[Attribute, ...] = field(default_factory=tuple)

    def attribute(self, attribute_id: int) -> bytes | None:
        for a in self.attributes:
            if a.attribute_id == attribute_id:
                return a.value
        return None


@dataclass(frozen=True)
class ConfigReport:
    """ConfigReport, the event-info of MDC_NOTI_CONFIG."""

    config_report_id: int
    objects: tuple[ConfigObject, ...]

    def encode(self) -> bytes:
        return _u16(self.config_report_id) + _list([
            _u16(o.obj_class) + _u16(o.obj_handle) + _list([a.encode() for a in o.attributes])
            for o in self.objects])

    @classmethod
    def decode(cls, data: bytes) -> ConfigReport:
        r = _Reader(data)
        config_id = r.u16()
        count, items = _read_list(r)
        objects = []
        for _ in range(count):
            obj_class, handle = items.u16(), items.u16()
            objects.append(ConfigObject(obj_class, handle, _attributes(items)))
        items.done()
        r.done()
        return cls(config_id, tuple(objects))


@dataclass(frozen=True)
class ConfigReportResponse:
    """ConfigReportRsp, the event-reply-info that answers a configuration report."""

    config_report_id: int
    result: int = ACCEPTED_CONFIG

    def encode(self) -> bytes:
        return _u16(self.config_report_id) + _u16(self.result)

    @classmethod
    def decode(cls, data: bytes) -> ConfigReportResponse:
        r = _Reader(data)
        found = cls(r.u16(), r.u16())
        r.done()
        return found
