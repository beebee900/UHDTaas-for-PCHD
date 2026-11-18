"""Device configurations and the values inside fixed scan reports.

A configuration lists the agent's numeric metric objects. Each object's Attribute-Value-Map
says which attributes a fixed scan report carries for it, in order:
- MDC_ATTR_NU_VAL_OBS_BASIC: one SFLOAT
- MDC_ATTR_NU_VAL_OBS_SIMP: one FLOAT
- MDC_ATTR_NU_CMPD_VAL_OBS_BASIC: count, length, then one SFLOAT per MDC_ATTR_ID_PHYSIO_LIST entry
- MDC_ATTR_TIME_STAMP_ABS: AbsoluteTime, eight BCD octets (century, year, month, day, hour,
  minute, second, hundredths)

Sources (Antidote, commit dbb27422):
- standard configurations: `src/specializations/blood_pressure_monitor.c` (0x02BC),
  `glucometer.c` (0x06A4), `weighing_scale.c` (0x05DC), `pulse_oximeter.c` (0x0190)
- the scale configuration with height and BMI: the Annex H configuration report example
  `tests/resources/apdu/H221_ID_05DC`
- AbsoluteTime: `src/util/dateutil.c`

The spirometer configuration is an extended configuration of this project. It reports peak
expiratory flow and FEV1 with verified MDC terms in the same layout as the glucometer. It is not
the IEEE 11073-10421 standard configuration, which no public source describes.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime

from edge.devices.decode import medfloat
from edge.devices.decode.phd import nomenclature as nom
from edge.devices.decode.phd.apdu import (
    EXTENDED_CONFIG_START,
    Attribute,
    ConfigObject,
    ConfigReport,
    DecodeError,
    ObservationScanFixed,
    ScanReportFixed,
)
from edge.devices.decode.phd.nomenclature import Nom

BASIC = nom.MDC_ATTR_NU_VAL_OBS_BASIC.term
SIMPLE = nom.MDC_ATTR_NU_VAL_OBS_SIMP.term
COMPOUND = nom.MDC_ATTR_NU_CMPD_VAL_OBS_BASIC.term
TIME_ABS = nom.MDC_ATTR_TIME_STAMP_ABS.term

# Metric-Spec-Small values used by the configurations below.
SPEC_INTERMITTENT_STORED_AGENT_INIT = 0xF040
SPEC_STORED_AGENT_INIT = 0x4040


def _u16(v: int) -> bytes:
    return v.to_bytes(2, "big")


def _from_u16(b: bytes) -> int:
    return int.from_bytes(b, "big")


def _bcd(n: int) -> int:
    return (n // 10) << 4 | n % 10


def _from_bcd(b: int) -> int:
    return 10 * (b >> 4) + (b & 0xF)


def encode_absolute_time(t: datetime) -> bytes:
    parts = (t.year // 100, t.year % 100, t.month, t.day, t.hour, t.minute, t.second,
             t.microsecond // 10_000)
    return bytes(_bcd(p) for p in parts)


def decode_absolute_time(b: bytes) -> datetime | None:
    """The time, or None when the octets are all zero or not a valid date."""
    if len(b) != 8:
        raise DecodeError("AbsoluteTime is eight octets")
    if not any(b):
        return None
    c, y, mo, d, h, mi, s, f = (_from_bcd(x) for x in b)
    try:
        return datetime(100 * c + y, mo, d, h, mi, s, f * 10_000)
    except ValueError:
        return None


@dataclass(frozen=True)
class MetricObject:
    """One numeric metric object (MDC_MOC_VMO_METRIC_NU) of a configuration."""

    handle: int
    type: Nom
    unit: Nom
    value_map: tuple[tuple[int, int], ...]
    """(attribute term code, octet length) of each attribute in a fixed scan report."""
    spec_small: int = SPEC_INTERMITTENT_STORED_AGENT_INIT
    struct_small: int | None = None
    components: tuple[Nom, ...] = ()
    """MDC_ATTR_ID_PHYSIO_LIST terms of a compound value."""
    source_handle: int | None = None

    def config_object(self) -> ConfigObject:
        attrs = [Attribute(nom.MDC_ATTR_ID_TYPE.term,
                           _u16(self.type.partition) + _u16(self.type.term)),
                 Attribute(nom.MDC_ATTR_METRIC_SPEC_SMALL.term, _u16(self.spec_small))]
        if self.struct_small is not None:
            attrs.append(Attribute(nom.MDC_ATTR_METRIC_STRUCT_SMALL.term,
                                   _u16(self.struct_small)))
        if self.components:
            ids = b"".join(_u16(c.term) for c in self.components)
            attrs.append(Attribute(nom.MDC_ATTR_ID_PHYSIO_LIST.term,
                                   _u16(len(self.components)) + _u16(len(ids)) + ids))
        attrs.append(Attribute(nom.MDC_ATTR_UNIT_CODE.term, _u16(self.unit.term)))
        if self.source_handle is not None:
            attrs.append(Attribute(nom.MDC_ATTR_SOURCE_HANDLE_REF.term,
                                   _u16(self.source_handle)))
        entries = b"".join(_u16(a) + _u16(n) for a, n in self.value_map)
        attrs.append(Attribute(nom.MDC_ATTR_ATTRIBUTE_VAL_MAP.term,
                               _u16(len(self.value_map)) + _u16(len(entries)) + entries))
        return ConfigObject(nom.MDC_MOC_VMO_METRIC_NU.term, self.handle, tuple(attrs))

    @classmethod
    def from_config_object(cls, obj: ConfigObject) -> MetricObject:
        if obj.obj_class != nom.MDC_MOC_VMO_METRIC_NU.term:
            raise DecodeError(f"object class {obj.obj_class} is not a numeric metric")
        type_ = obj.attribute(nom.MDC_ATTR_ID_TYPE.term)
        unit = obj.attribute(nom.MDC_ATTR_UNIT_CODE.term)
        value_map = obj.attribute(nom.MDC_ATTR_ATTRIBUTE_VAL_MAP.term)
        if type_ is None or unit is None or value_map is None:
            raise DecodeError(f"metric {obj.obj_handle} lacks its type, unit or value map")
        spec = obj.attribute(nom.MDC_ATTR_METRIC_SPEC_SMALL.term)
        struct = obj.attribute(nom.MDC_ATTR_METRIC_STRUCT_SMALL.term)
        physio = obj.attribute(nom.MDC_ATTR_ID_PHYSIO_LIST.term)
        source = obj.attribute(nom.MDC_ATTR_SOURCE_HANDLE_REF.term)
        pairs = tuple((_from_u16(value_map[i:i + 2]), _from_u16(value_map[i + 2:i + 4]))
                      for i in range(4, len(value_map), 4))
        partition = _from_u16(type_[:2])
        components = tuple(Nom(partition, _from_u16(physio[i:i + 2]))
                           for i in range(4, len(physio), 2)) if physio else ()
        return cls(obj.obj_handle, Nom(partition, _from_u16(type_[2:4])),
                   Nom(nom.PART_DIM, _from_u16(unit)), pairs,
                   _from_u16(spec) if spec else SPEC_INTERMITTENT_STORED_AGENT_INIT,
                   _from_u16(struct) if struct else None, components,
                   _from_u16(source) if source else None)


@dataclass(frozen=True)
class Configuration:
    config_id: int
    objects: tuple[MetricObject, ...]

    @property
    def extended(self) -> bool:
        return self.config_id >= EXTENDED_CONFIG_START

    def by_handle(self, handle: int) -> MetricObject:
        for o in self.objects:
            if o.handle == handle:
                return o
        raise DecodeError(f"configuration 0x{self.config_id:04X} has no object {handle}")

    def report(self) -> ConfigReport:
        """The configuration report an agent sends for an extended configuration."""
        return ConfigReport(self.config_id, tuple(o.config_object() for o in self.objects))

    @classmethod
    def from_report(cls, report: ConfigReport) -> Configuration:
        return cls(report.config_report_id,
                   tuple(MetricObject.from_config_object(o) for o in report.objects))


@dataclass(frozen=True)
class Measurement:
    handle: int
    values: tuple[tuple[Nom, float], ...]
    """(term, value) pairs: one for a simple metric, one per component for a compound one."""
    unit: Nom
    time: datetime | None = None


def decode_scan(scan: ScanReportFixed, config: Configuration) -> list[Measurement]:
    out = []
    for obs in scan.observations:
        obj = config.by_handle(obs.obj_handle)
        data, pos = obs.data, 0
        values: tuple[tuple[Nom, float], ...] = ()
        time = None
        for attr, length in obj.value_map:
            chunk = data[pos:pos + length]
            if len(chunk) != length:
                raise DecodeError(f"observation {obs.obj_handle} is shorter than its value map")
            pos += length
            if attr == BASIC:
                values = ((obj.type, medfloat.decode_sfloat(_from_u16(chunk))),)
            elif attr == SIMPLE:
                values = ((obj.type, medfloat.decode_float(int.from_bytes(chunk, "big"))),)
            elif attr == COMPOUND:
                count = _from_u16(chunk[:2])
                raw = [medfloat.decode_sfloat(_from_u16(chunk[4 + 2 * i:6 + 2 * i]))
                       for i in range(count)]
                values = tuple(zip(obj.components, raw, strict=True))
            elif attr == TIME_ABS:
                time = decode_absolute_time(chunk)
        if pos != len(data):
            raise DecodeError(f"observation {obs.obj_handle} is longer than its value map")
        out.append(Measurement(obs.obj_handle, values, obj.unit, time))
    return out


def scan_report(config: Configuration, values: Mapping[int, float | Sequence[float]],
                time: datetime | None = None, scan_report_no: int = 0) -> ScanReportFixed:
    """A fixed scan report with one observation per handle in `values`.

    A compound object takes one value per component. Attributes this codec does not produce
    are written as zero octets.
    """
    observations = []
    for handle, value in values.items():
        obj = config.by_handle(handle)
        parts = [float(value)] if isinstance(value, int | float) else [float(v) for v in value]
        if len(parts) != max(1, len(obj.components)):
            raise ValueError(f"object {handle} takes {max(1, len(obj.components))} values")
        data = b""
        for attr, length in obj.value_map:
            if attr == BASIC:
                chunk = _u16(medfloat.encode_sfloat(parts[0]))
            elif attr == SIMPLE:
                chunk = medfloat.encode_float(parts[0]).to_bytes(4, "big")
            elif attr == COMPOUND:
                body = b"".join(_u16(medfloat.encode_sfloat(v)) for v in parts)
                chunk = _u16(len(parts)) + _u16(len(body)) + body
            elif attr == TIME_ABS:
                chunk = encode_absolute_time(time) if time else bytes(8)
            else:
                chunk = bytes(length)
            if len(chunk) != length:
                raise ValueError(f"object {handle}: attribute {attr} is {length} octets")
            data += chunk
        observations.append(ObservationScanFixed(handle, data))
    return ScanReportFixed(tuple(observations), scan_report_no)


_TIMED_BASIC = ((BASIC, 2), (TIME_ABS, 8))
_TIMED_SIMPLE = ((SIMPLE, 4), (TIME_ABS, 8))

BLOOD_PRESSURE = Configuration(0x02BC, (
    MetricObject(1, nom.MDC_PRESS_BLD_NONINV, nom.MDC_DIM_MMHG, ((COMPOUND, 10), (TIME_ABS, 8)),
                 struct_small=0x0303,
                 components=(nom.MDC_PRESS_BLD_NONINV_SYS, nom.MDC_PRESS_BLD_NONINV_DIA,
                             nom.MDC_PRESS_BLD_NONINV_MEAN)),
    MetricObject(2, nom.MDC_PULS_RATE_NON_INV, nom.MDC_DIM_BEAT_PER_MIN, _TIMED_BASIC),
))
GLUCOMETER = Configuration(0x06A4, (
    MetricObject(1, nom.MDC_CONC_GLU_CAPILLARY_WHOLEBLOOD, nom.MDC_DIM_MILLI_G_PER_DL,
                 _TIMED_BASIC),
))
WEIGHING_SCALE = Configuration(0x05DC, (
    MetricObject(1, nom.MDC_MASS_BODY_ACTUAL, nom.MDC_DIM_KILO_G, _TIMED_SIMPLE),
))
WEIGHING_SCALE_BMI = Configuration(0x4000, (
    MetricObject(1, nom.MDC_MASS_BODY_ACTUAL, nom.MDC_DIM_KILO_G, _TIMED_SIMPLE),
    MetricObject(2, nom.MDC_LEN_BODY_ACTUAL, nom.MDC_DIM_CENTI_M, _TIMED_SIMPLE,
                 spec_small=0xF048),
    MetricObject(3, nom.MDC_RATIO_MASS_BODY_LEN_SQ, nom.MDC_DIM_KG_PER_M_SQ, _TIMED_SIMPLE,
                 spec_small=0xF042, source_handle=1),
))
PULSE_OXIMETER = Configuration(0x0190, (
    MetricObject(1, nom.MDC_PULS_OXIM_SAT_O2, nom.MDC_DIM_PERCENT, ((BASIC, 2),),
                 spec_small=SPEC_STORED_AGENT_INIT),
    MetricObject(10, nom.MDC_PULS_OXIM_PULS_RATE, nom.MDC_DIM_BEAT_PER_MIN, ((BASIC, 2),),
                 spec_small=SPEC_STORED_AGENT_INIT),
))
SPIROMETER = Configuration(0x4001, (
    MetricObject(1, nom.MDC_FLOW_AWAY_EXP_FORCED_PEAK, nom.MDC_DIM_X_L_PER_MIN, _TIMED_BASIC),
    MetricObject(2, nom.MDC_VOL_AWAY_EXP_FORCED_1S, nom.MDC_DIM_X_L, _TIMED_BASIC),
))

STANDARD: dict[int, Configuration] = {
    c.config_id: c for c in (BLOOD_PRESSURE, GLUCOMETER, WEIGHING_SCALE, PULSE_OXIMETER)
}
"""Standard configurations a manager knows without a configuration report."""
