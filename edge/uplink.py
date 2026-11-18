"""The edge's client of the AHDT gRPC `ObservationService.Ingest` (design 03, 3.15).

The edge authenticates with a service token in the `authorization` metadata. With mutual TLS
configured, the channel presents the edge certificate from the local CA (design 07, 7.1.1).
`UNAVAILABLE` and `DEADLINE_EXCEEDED` mean the link or the AHDT is down: the call raises
`LinkDown` and the outbox keeps the batch.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

import grpc

from contracts.proto import ahdt_pb2, ahdt_pb2_grpc
from edge.outbox import Ack, LinkDown

LINK_ERRORS = frozenset({grpc.StatusCode.UNAVAILABLE, grpc.StatusCode.DEADLINE_EXCEEDED})


def observation(o: Mapping[str, Any]) -> Any:
    """An ingestion payload as an `ahdt.v1.Observation`."""
    msg = ahdt_pb2.Observation(
        record_id=str(o["record_id"]), idempotency_key=str(o.get("idempotency_key") or ""),
        hdt_id=str(o.get("hdt_id") or ""), dt=str(o.get("dt") or ""),
        code=ahdt_pb2.Coding(system=o["code"]["system"], code=o["code"]["code"],
                             display=o["code"].get("display") or ""),
        alt_codes=[ahdt_pb2.Coding(system=c["system"], code=c["code"],
                                   display=c.get("display") or "")
                   for c in o.get("alt_codes", [])],
        unit=str(o.get("unit") or "1"), device_id=str(o.get("device_id") or ""),
        source=str(o.get("source") or "device"), version=int(o.get("version", 1)))
    msg.effective_time.FromDatetime(datetime.fromisoformat(str(o["effective_time"])))
    if o.get("sim_time") is not None:
        msg.sim_time = float(o["sim_time"])
    v = o["value"]
    if isinstance(v, bool):
        msg.flag = v
    elif isinstance(v, int | float):
        msg.number = float(v)
    elif isinstance(v, str):
        msg.text = v
    elif isinstance(v, Mapping):
        msg.waveform.samples.extend(float(x) for x in v["array"])
        msg.waveform.period_ms = float(v["period_ms"])
    else:
        raise ValueError(f"no wire form for value {v!r}")
    return msg


def credentials(pki_dir: Path, name: str = "edge") -> grpc.ChannelCredentials:
    return grpc.ssl_channel_credentials(
        root_certificates=(pki_dir / "ca.crt").read_bytes(),
        private_key=(pki_dir / f"{name}.key").read_bytes(),
        certificate_chain=(pki_dir / f"{name}.crt").read_bytes())


class GrpcIngestor:
    def __init__(self, target: str, token: Callable[[], str], *,
                 tls: grpc.ChannelCredentials | None = None, timeout_s: float = 120.0) -> None:
        self.target = target
        self.token = token
        self.tls = tls
        self.timeout_s = timeout_s
        self.compression = grpc.Compression.NoCompression
        self._channel: Any = None

    def channel(self) -> Any:
        if self._channel is None:
            self._channel = (grpc.aio.secure_channel(self.target, self.tls) if self.tls
                             else grpc.aio.insecure_channel(self.target))
        return self._channel

    async def ingest(self, observations: Sequence[Mapping[str, Any]]) -> Ack:
        generated: Any = ahdt_pb2_grpc
        stub = generated.ObservationServiceStub(self.channel())
        messages = [observation(o) for o in observations]
        try:
            ack = await stub.Ingest(iter(messages), timeout=self.timeout_s,
                                    metadata=(("authorization", f"Bearer {self.token()}"),),
                                    compression=self.compression)
        except grpc.aio.AioRpcError as exc:
            if exc.code() in LINK_ERRORS:
                raise LinkDown(f"{self.target}: {exc.code().name}") from exc
            raise
        return Ack(ack.accepted, ack.duplicates, ack.rejected, tuple(ack.rejected_ids))

    async def close(self) -> None:
        if self._channel is not None:
            await self._channel.close()
            self._channel = None
