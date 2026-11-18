"""gRPC surfaces of the AHDT (design 03, 3.15): observation ingest and stream, inference.

The edge tier calls `Ingest` with a service token in the `authorization` metadata. Each
batch goes through the ingestion pipeline. Every observation carries an idempotency key,
so a batch re-sent after a link cut is not stored twice (NFR6).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from datetime import UTC, datetime
from typing import Any

import grpc
from google.protobuf import json_format, struct_pb2, timestamp_pb2

from ahdt.ingest.harmonise import RawObservation
from ahdt.ingest.pipeline import IngestPipeline
from atra.contracts import Code, ModelOutput, Waveform
from atra.security import InvalidToken, TokenVerifier, bearer
from contracts.proto import ahdt_pb2, ahdt_pb2_grpc


def _verify(context: Any, verifier: TokenVerifier) -> None:
    meta = dict(context.invocation_metadata())
    try:
        claims = verifier.verify(bearer(meta.get("authorization")))
    except InvalidToken as exc:
        raise _Abort(grpc.StatusCode.UNAUTHENTICATED, str(exc)) from exc
    if not claims.is_service:
        raise _Abort(grpc.StatusCode.PERMISSION_DENIED, "only service clients may call this")


class _Abort(Exception):
    def __init__(self, code: grpc.StatusCode, detail: str) -> None:
        super().__init__(detail)
        self.code, self.detail = code, detail


def _raw(obs: Any) -> RawObservation:
    kind = obs.WhichOneof("value")
    value: Any
    if kind == "number":
        value = float(obs.number)
    elif kind == "text":
        value = str(obs.text)
    elif kind == "flag":
        value = bool(obs.flag)
    elif kind == "waveform":
        value = Waveform(array=list(obs.waveform.samples), period_ms=obs.waveform.period_ms)
    else:
        raise ValueError("the observation carries no value")
    return RawObservation(
        record_id=obs.record_id, hdt_id=obs.hdt_id or None, value=value, unit=obs.unit,
        code=Code(system=obs.code.system, code=obs.code.code, display=obs.code.display or None),
        alt_codes=[Code(system=c.system, code=c.code) for c in obs.alt_codes],
        effective_time=obs.effective_time.ToDatetime(tzinfo=UTC),
        sim_time=obs.sim_time if obs.HasField("sim_time") else None,
        device_id=obs.device_id or None, source=obs.source or "device",
        version=max(1, obs.version), idempotency_key=obs.idempotency_key or None)


class ObservationServicer(ahdt_pb2_grpc.ObservationServiceServicer):
    def __init__(self, pipeline: IngestPipeline, verifier: TokenVerifier) -> None:
        self.pipeline = pipeline
        self.backends = pipeline.backends
        self.verifier = verifier

    async def Ingest(self, request_iterator: AsyncIterator[Any], context: Any) -> Any:
        try:
            _verify(context, self.verifier)
        except _Abort as exc:
            await context.abort(exc.code, exc.detail)
        raws: list[RawObservation] = []
        invalid: list[str] = []
        async for obs in request_iterator:
            try:
                raws.append(_raw(obs))
            except ValueError:
                invalid.append(obs.record_id)
        result = await self.pipeline.process(raws)
        rejected = invalid + [r.record_id for r in result.rejected] + result.dropped
        return ahdt_pb2.IngestAck(accepted=len(result.accepted),
                                  duplicates=len(result.duplicates), rejected=len(rejected),
                                  rejected_ids=rejected)

    async def Stream(self, request: Any, context: Any) -> AsyncIterator[Any]:
        try:
            _verify(context, self.verifier)
        except _Abort as exc:
            await context.abort(exc.code, exc.detail)
        since = request.since.ToDatetime(tzinfo=UTC) if request.HasField("since") else None
        codes = list(request.codes) or await self.backends.timeseries.codes(request.hdt_id)
        for code in codes:
            for p in await self.backends.timeseries.query(request.hdt_id, code, start=since):
                ts = timestamp_pb2.Timestamp()
                ts.FromDatetime(p.t)
                obs = ahdt_pb2.Observation(hdt_id=request.hdt_id, unit=p.unit,
                                           quality=p.quality, version=p.version,
                                           effective_time=ts,
                                           code=ahdt_pb2.Coding(system="http://loinc.org",
                                                                code=code))
                if isinstance(p.v, bool):
                    obs.flag = p.v
                elif isinstance(p.v, int | float):
                    obs.number = float(p.v)
                else:
                    obs.text = str(p.v)
                yield obs


type InferFn = Callable[[str, str, str, Mapping[str, Any]], Awaitable[ModelOutput]]


class InferenceServicer(ahdt_pb2_grpc.InferenceServiceServicer):
    def __init__(self, verifier: TokenVerifier, infer: InferFn) -> None:
        self.verifier = verifier
        self.infer = infer

    async def Infer(self, request: Any, context: Any) -> Any:
        try:
            _verify(context, self.verifier)
        except _Abort as exc:
            await context.abort(exc.code, exc.detail)
        inputs = json_format.MessageToDict(request.inputs)
        try:
            out = await self.infer(request.model_id, request.version, request.hdt_id, inputs)
        except LookupError as exc:
            await context.abort(grpc.StatusCode.NOT_FOUND, str(exc))
        values, uncertainty = struct_pb2.Struct(), struct_pb2.Struct()
        values.update(out.values)
        uncertainty.update({k: u.model_dump(mode="json", by_alias=True)
                            for k, u in out.uncertainty.items()})
        return ahdt_pb2.InferResponse(output_id=out.output_id, model_id=out.model_id,
                                      version=out.version, values=values,
                                      uncertainty=uncertainty)


async def start(pipeline: IngestPipeline, verifier: TokenVerifier, port: int,
                infer: InferFn) -> tuple[Any, int]:
    """Start the gRPC server; port 0 picks a free port. Returns the server and its port."""
    server = grpc.aio.server()
    generated: Any = ahdt_pb2_grpc
    generated.add_ObservationServiceServicer_to_server(
        ObservationServicer(pipeline, verifier), server)
    generated.add_InferenceServiceServicer_to_server(InferenceServicer(verifier, infer), server)
    bound = server.add_insecure_port(f"127.0.0.1:{port}")
    await server.start()
    return server, bound


def timestamp(dt: datetime) -> Any:
    ts = timestamp_pb2.Timestamp()
    ts.FromDatetime(dt)
    return ts
