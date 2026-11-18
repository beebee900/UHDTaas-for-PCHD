"""IEEE 11073-20601 personal health device exchange: APDUs, configurations, scan reports.

The helpers build the messages of one measurement session:
1. agent → manager: `association_request`
2. manager → agent: `association_response` (`ACCEPTED`, or `ACCEPTED_UNKNOWN_CONFIG` for an
   extended configuration)
3. agent → manager, extended configuration only: `config_event`, answered by `acknowledge`
   with a `ConfigReportResponse`
4. agent → manager: `scan_event`, answered by `acknowledge`
5. either side: `ReleaseRequest`, answered by `ReleaseResponse`

Field values of the manager's response follow Antidote's manager
(`src/communication/association.c`, commit dbb27422).
"""

from __future__ import annotations

from edge.devices.decode.phd import nomenclature
from edge.devices.decode.phd.apdu import (
    ACCEPTED,
    ACCEPTED_UNKNOWN_CONFIG,
    DATA_PROTO_ID_20601,
    MANAGER_CONFIG_RESPONSE,
    SYS_TYPE_MANAGER,
    Abort,
    Apdu,
    AssociationInformation,
    AssociationRequest,
    AssociationResponse,
    ConfigReport,
    ConfigReportResponse,
    DataProto,
    DecodeError,
    EventReport,
    EventReportResult,
    ReleaseRequest,
    ReleaseResponse,
    ScanReportFixed,
    UnsupportedApdu,
    decode,
    encode,
)
from edge.devices.decode.phd.configs import (
    STANDARD,
    Configuration,
    Measurement,
    MetricObject,
    decode_scan,
    scan_report,
)


def association_request(system_id: bytes, dev_config_id: int, *,
                        data_req_mode_flags: int = 0, init_agent_count: int = 0,
                        init_manager_count: int = 0) -> AssociationRequest:
    """An agent's AARQ offering the 20601 protocol with MDER encoding."""
    info = AssociationInformation(system_id, dev_config_id,
                                  data_req_mode_flags=data_req_mode_flags,
                                  data_req_init_agent_count=init_agent_count,
                                  data_req_init_manager_count=init_manager_count)
    return AssociationRequest((DataProto(DATA_PROTO_ID_20601, info.encode()),))


def association_response(result: int, manager_system_id: bytes) -> AssociationResponse:
    info = AssociationInformation(manager_system_id, MANAGER_CONFIG_RESPONSE,
                                  system_type=SYS_TYPE_MANAGER)
    return AssociationResponse(result, DataProto(DATA_PROTO_ID_20601, info.encode()))


def scan_event(invoke_id: int, scan: ScanReportFixed) -> EventReport:
    return EventReport(invoke_id, nomenclature.MDC_NOTI_SCAN_REPORT_FIXED.term, scan.encode())


def config_event(invoke_id: int, config: Configuration) -> EventReport:
    return EventReport(invoke_id, nomenclature.MDC_NOTI_CONFIG.term, config.report().encode())


def acknowledge(event: EventReport, reply_info: bytes = b"") -> EventReportResult:
    """The manager's confirmation of a confirmed event report."""
    return EventReportResult(event.invoke_id, event.event_type, reply_info, event.obj_handle)


__all__ = [
    "ACCEPTED", "ACCEPTED_UNKNOWN_CONFIG", "STANDARD", "Abort", "Apdu", "AssociationInformation",
    "AssociationRequest", "AssociationResponse", "ConfigReport", "ConfigReportResponse",
    "Configuration", "DecodeError", "EventReport", "EventReportResult", "Measurement",
    "MetricObject", "ReleaseRequest", "ReleaseResponse", "ScanReportFixed", "UnsupportedApdu",
    "acknowledge", "association_request", "association_response", "config_event", "decode",
    "decode_scan", "encode", "scan_event", "scan_report",
]
