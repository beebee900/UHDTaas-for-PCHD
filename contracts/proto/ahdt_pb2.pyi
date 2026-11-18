import datetime

from google.protobuf import struct_pb2 as _struct_pb2
from google.protobuf import timestamp_pb2 as _timestamp_pb2
from google.protobuf.internal import containers as _containers
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Coding(_message.Message):
    __slots__ = ("system", "code", "display")
    SYSTEM_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    DISPLAY_FIELD_NUMBER: _ClassVar[int]
    system: str
    code: str
    display: str
    def __init__(self, system: _Optional[str] = ..., code: _Optional[str] = ..., display: _Optional[str] = ...) -> None: ...

class Waveform(_message.Message):
    __slots__ = ("samples", "period_ms")
    SAMPLES_FIELD_NUMBER: _ClassVar[int]
    PERIOD_MS_FIELD_NUMBER: _ClassVar[int]
    samples: _containers.RepeatedScalarFieldContainer[float]
    period_ms: float
    def __init__(self, samples: _Optional[_Iterable[float]] = ..., period_ms: _Optional[float] = ...) -> None: ...

class Observation(_message.Message):
    __slots__ = ("record_id", "hdt_id", "dt", "code", "alt_codes", "number", "text", "flag", "waveform", "unit", "effective_time", "sim_time", "device_id", "source", "quality", "consent_tag", "provenance_id", "version", "idempotency_key")
    RECORD_ID_FIELD_NUMBER: _ClassVar[int]
    HDT_ID_FIELD_NUMBER: _ClassVar[int]
    DT_FIELD_NUMBER: _ClassVar[int]
    CODE_FIELD_NUMBER: _ClassVar[int]
    ALT_CODES_FIELD_NUMBER: _ClassVar[int]
    NUMBER_FIELD_NUMBER: _ClassVar[int]
    TEXT_FIELD_NUMBER: _ClassVar[int]
    FLAG_FIELD_NUMBER: _ClassVar[int]
    WAVEFORM_FIELD_NUMBER: _ClassVar[int]
    UNIT_FIELD_NUMBER: _ClassVar[int]
    EFFECTIVE_TIME_FIELD_NUMBER: _ClassVar[int]
    SIM_TIME_FIELD_NUMBER: _ClassVar[int]
    DEVICE_ID_FIELD_NUMBER: _ClassVar[int]
    SOURCE_FIELD_NUMBER: _ClassVar[int]
    QUALITY_FIELD_NUMBER: _ClassVar[int]
    CONSENT_TAG_FIELD_NUMBER: _ClassVar[int]
    PROVENANCE_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    IDEMPOTENCY_KEY_FIELD_NUMBER: _ClassVar[int]
    record_id: str
    hdt_id: str
    dt: str
    code: Coding
    alt_codes: _containers.RepeatedCompositeFieldContainer[Coding]
    number: float
    text: str
    flag: bool
    waveform: Waveform
    unit: str
    effective_time: _timestamp_pb2.Timestamp
    sim_time: float
    device_id: str
    source: str
    quality: str
    consent_tag: str
    provenance_id: str
    version: int
    idempotency_key: str
    def __init__(self, record_id: _Optional[str] = ..., hdt_id: _Optional[str] = ..., dt: _Optional[str] = ..., code: _Optional[_Union[Coding, _Mapping]] = ..., alt_codes: _Optional[_Iterable[_Union[Coding, _Mapping]]] = ..., number: _Optional[float] = ..., text: _Optional[str] = ..., flag: _Optional[bool] = ..., waveform: _Optional[_Union[Waveform, _Mapping]] = ..., unit: _Optional[str] = ..., effective_time: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ..., sim_time: _Optional[float] = ..., device_id: _Optional[str] = ..., source: _Optional[str] = ..., quality: _Optional[str] = ..., consent_tag: _Optional[str] = ..., provenance_id: _Optional[str] = ..., version: _Optional[int] = ..., idempotency_key: _Optional[str] = ...) -> None: ...

class StreamRequest(_message.Message):
    __slots__ = ("hdt_id", "codes", "since")
    HDT_ID_FIELD_NUMBER: _ClassVar[int]
    CODES_FIELD_NUMBER: _ClassVar[int]
    SINCE_FIELD_NUMBER: _ClassVar[int]
    hdt_id: str
    codes: _containers.RepeatedScalarFieldContainer[str]
    since: _timestamp_pb2.Timestamp
    def __init__(self, hdt_id: _Optional[str] = ..., codes: _Optional[_Iterable[str]] = ..., since: _Optional[_Union[datetime.datetime, _timestamp_pb2.Timestamp, _Mapping]] = ...) -> None: ...

class IngestAck(_message.Message):
    __slots__ = ("accepted", "duplicates", "rejected", "rejected_ids")
    ACCEPTED_FIELD_NUMBER: _ClassVar[int]
    DUPLICATES_FIELD_NUMBER: _ClassVar[int]
    REJECTED_FIELD_NUMBER: _ClassVar[int]
    REJECTED_IDS_FIELD_NUMBER: _ClassVar[int]
    accepted: int
    duplicates: int
    rejected: int
    rejected_ids: _containers.RepeatedScalarFieldContainer[str]
    def __init__(self, accepted: _Optional[int] = ..., duplicates: _Optional[int] = ..., rejected: _Optional[int] = ..., rejected_ids: _Optional[_Iterable[str]] = ...) -> None: ...

class InferRequest(_message.Message):
    __slots__ = ("model_id", "version", "hdt_id", "inputs")
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    HDT_ID_FIELD_NUMBER: _ClassVar[int]
    INPUTS_FIELD_NUMBER: _ClassVar[int]
    model_id: str
    version: str
    hdt_id: str
    inputs: _struct_pb2.Struct
    def __init__(self, model_id: _Optional[str] = ..., version: _Optional[str] = ..., hdt_id: _Optional[str] = ..., inputs: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...

class InferResponse(_message.Message):
    __slots__ = ("output_id", "model_id", "version", "values", "uncertainty")
    OUTPUT_ID_FIELD_NUMBER: _ClassVar[int]
    MODEL_ID_FIELD_NUMBER: _ClassVar[int]
    VERSION_FIELD_NUMBER: _ClassVar[int]
    VALUES_FIELD_NUMBER: _ClassVar[int]
    UNCERTAINTY_FIELD_NUMBER: _ClassVar[int]
    output_id: str
    model_id: str
    version: str
    values: _struct_pb2.Struct
    uncertainty: _struct_pb2.Struct
    def __init__(self, output_id: _Optional[str] = ..., model_id: _Optional[str] = ..., version: _Optional[str] = ..., values: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ..., uncertainty: _Optional[_Union[_struct_pb2.Struct, _Mapping]] = ...) -> None: ...
