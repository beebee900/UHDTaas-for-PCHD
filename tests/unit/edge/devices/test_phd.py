"""IEEE 11073-20601 codec against the Annex H example APDUs as copied in the Antidote test
resources (github.com/signove/antidote, tests/resources/apdu, commit dbb27422)."""

import csv
from dataclasses import replace
from datetime import datetime

import pytest
from hypothesis import given
from hypothesis import strategies as st

from atra.config import ROOT
from edge.devices.decode import phd
from edge.devices.decode.phd import configs, nomenclature
from edge.devices.decode.phd.apdu import (
    ConfigReport,
    ConfigReportResponse,
    DataProto,
    DecodeError,
    UnsupportedApdu,
)

VECTORS = {
    "H211_ID_02BC": "e2000032800000000001002a5079002680000000a00080000000000000000080000000"
                    "08112233445566770702bc8480010100000000",
    "H211_ID_05DC": "e2000032800000000001002a5079002680000000a00080000000000000000080000000"
                    "08112233445566778805dc0001010000000000",
    "H212": "e300002c00035079002680000000800080000000000000008000000000081122334455667788"
            "00000000000000000000",
    "H221_ID_05DC": "e70000a200a012350101009a0000ffffffff0d1c009040000003008a0006000100040024"
                    "092f00040002e1400a460002f0400996000206c30a55000c000200080a5600040990000800"
                    "06000200040024092f00040002e1440a460002f0480996000205110a55000c000200080a56"
                    "000409900008000600030005002a092f00040002e1500a460002f0420996000207a00a4700"
                    "0200010a55000c000200080a56000409900008",
    "H222": "e7000016001443210201000e0000000000000d1c000440000000",
    "H232": "e700000e000c345601030006000000000000",
    "H241_ID_02BC": "e700003e003c0054010100360000004900500d1d002cf00000000002002400010012000300"
                    "0600780050006420071206121000000002000af2582007120612100000",
    "H241_ID_05DC": "e700005a00581236010100520000000000000d1d0048f0000000000400400001000cff0002"
                    "fa20071206121000000003000cff0000f320071206121000000001000cff0002f820071206"
                    "200500000003000cff0000f22007120620050000",
    "H242": "e7000012001043210201000a0000000000000d1d0000",
}


def vector(name):
    return bytes.fromhex(VECTORS[name])


@pytest.mark.parametrize("name", [n for n in VECTORS if n != "H232"])
def test_annex_h_vectors_round_trip(name):
    assert phd.encode(phd.decode(vector(name))) == vector(name)


def test_association_request_fields():
    aarq = phd.decode(vector("H211_ID_02BC"))
    assert isinstance(aarq, phd.AssociationRequest)
    info = aarq.phd
    assert info.dev_config_id == 0x02BC and info.system_id == bytes.fromhex("1122334455667707")
    assert info.system_type == 0x00800000


def test_association_response_from_helper_matches_h212():
    aare = phd.association_response(phd.ACCEPTED_UNKNOWN_CONFIG, bytes.fromhex("1122334455667788"))
    assert phd.encode(aare) == vector("H212")


def test_bp_scan_report_with_standard_configuration():
    event = phd.decode(vector("H241_ID_02BC"))
    assert isinstance(event, phd.EventReport) and event.confirmed
    scan = phd.ScanReportFixed.decode(event.event_info)
    cuff, pulse = phd.decode_scan(scan, phd.STANDARD[0x02BC])
    assert [(t, v) for t, v in cuff.values] == [
        (nomenclature.MDC_PRESS_BLD_NONINV_SYS, 120.0),
        (nomenclature.MDC_PRESS_BLD_NONINV_DIA, 80.0),
        (nomenclature.MDC_PRESS_BLD_NONINV_MEAN, 100.0)]
    assert cuff.unit == nomenclature.MDC_DIM_MMHG and cuff.time == datetime(2007, 12, 6, 12, 10)
    assert pulse.values == ((nomenclature.MDC_PULS_RATE_NON_INV, 60.0),)
    assert phd.encode(phd.acknowledge(event)).hex() == \
        "e7000012001000540201000a0000000000000d1d0000"


def test_scale_configuration_report_and_scan():
    event = phd.decode(vector("H221_ID_05DC"))
    config = phd.Configuration.from_report(ConfigReport.decode(event.event_info))
    assert config == configs.WEIGHING_SCALE_BMI
    assert config.report().encode() == event.event_info
    scan_event = phd.decode(vector("H241_ID_05DC"))
    found = phd.decode_scan(phd.ScanReportFixed.decode(scan_event.event_info), config)
    assert [m.values[0] for m in found[:2]] == [
        (nomenclature.MDC_MASS_BODY_ACTUAL, 76.2), (nomenclature.MDC_RATIO_MASS_BODY_LEN_SQ, 24.3)]
    ack = phd.acknowledge(event, ConfigReportResponse(config.config_id).encode())
    assert phd.encode(replace(ack, invoke_id=0x4321)) == vector("H222")


@pytest.mark.parametrize("config", [configs.BLOOD_PRESSURE, configs.GLUCOMETER,
                                    configs.WEIGHING_SCALE, configs.WEIGHING_SCALE_BMI,
                                    configs.PULSE_OXIMETER, configs.SPIROMETER])
@given(data=st.data())
def test_scan_reports_round_trip(config, data):
    def value(obj):
        word = st.builds(lambda m, e: m * 10.0 ** e, st.integers(-2045, 2045), st.integers(-2, 1))
        if obj.components:
            return data.draw(st.lists(word, min_size=len(obj.components),
                                      max_size=len(obj.components)))
        return data.draw(word)

    values = {o.handle: value(o) for o in config.objects}
    time = data.draw(st.none() | st.datetimes(datetime(2000, 1, 1), datetime(2099, 12, 31)))
    report = phd.scan_report(config, values, time, scan_report_no=data.draw(st.integers(0, 9)))
    event = phd.decode(phd.encode(phd.scan_event(7, report)))
    found = phd.decode_scan(phd.ScanReportFixed.decode(event.event_info), config)
    for m in found:
        sent = values[m.handle]
        sent = sent if isinstance(sent, list) else [sent]
        assert [v for _, v in m.values] == pytest.approx(sent, abs=0.5e-2)
        timed = any(a == configs.TIME_ABS for a, _ in config.by_handle(m.handle).value_map)
        if timed and time:
            assert m.time == time.replace(microsecond=time.microsecond // 10_000 * 10_000)


def test_session_messages_round_trip():
    request = phd.association_request(bytes(8), configs.SPIROMETER.config_id)
    assert phd.decode(phd.encode(request)) == request
    event = phd.config_event(1, configs.SPIROMETER)
    decoded = phd.decode(phd.encode(event))
    assert phd.Configuration.from_report(ConfigReport.decode(decoded.event_info)) == \
        configs.SPIROMETER
    for apdu in (phd.ReleaseRequest(), phd.ReleaseResponse(), phd.Abort(2)):
        assert phd.decode(phd.encode(apdu)) == apdu
    assert phd.encode(phd.ReleaseRequest()) == bytes.fromhex("e40000020000")


def test_unsupported_and_malformed():
    with pytest.raises(UnsupportedApdu):
        phd.decode(vector("H232"))
    with pytest.raises(DecodeError):
        phd.decode(vector("H212")[:-1])
    assert DataProto(1, b"").phd is None


def test_every_term_is_in_the_mdc_table():
    path = ROOT / "kb" / "terminology" / "mdc.csv"
    with path.open(encoding="utf-8") as fh:
        rows = {r["reference_id"]: r for r in csv.DictReader(fh)}
    for name, term in nomenclature.TERMS.items():
        row = rows[name]
        assert (int(row["partition"]), int(row["term_code"])) == term, name
        assert int(row["code"]) == term.cf and row["display"] == name
        assert row["source"].endswith(f"code={term.cf}")
    assert set(nomenclature.UCUM) <= set(nomenclature.TERMS.values())
