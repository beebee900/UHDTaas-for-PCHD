from datetime import UTC, datetime

import grpc
import pytest
from starlette.testclient import TestClient

from ahdt.app import build_app
from ahdt.grpc_server import timestamp
from atra.config import AHDTSettings
from atra.contracts import Role
from atra.personas import BY_KEY
from contracts.proto import ahdt_pb2, ahdt_pb2_grpc

HDT = BY_KEY["ao"].hdt_id


def observation(i, key=None):
    return ahdt_pb2.Observation(
        record_id=f"r-{i}", idempotency_key=key or f"k-{i}", hdt_id=HDT, dt="immune_lymphatic",
        code=ahdt_pb2.Coding(system="http://loinc.org", code="8310-5"), number=38.0 + i / 10,
        unit="Cel", effective_time=timestamp(datetime(2026, 10, 1, 8, i, tzinfo=UTC)),
        source="device", quality="ok", consent_tag="cons-1", provenance_id="atra:x", version=1)


def test_ingest_is_idempotent_and_streams_back(settings, backends):
    settings = settings.model_copy(update={"ahdt": AHDTSettings(grpc_port=0)})
    app = build_app(settings, backends=backends("ahdt"), local_llm=False)
    issuer = app.state.backends.issuer
    svc = [("authorization", f"Bearer {issuer.issue_service('edge-svc')}")]
    with TestClient(app), grpc.insecure_channel(f"127.0.0.1:{app.state.grpc_port}") as ch:
        stub = ahdt_pb2_grpc.ObservationServiceStub(ch)
        ack = stub.Ingest(iter([observation(i) for i in range(5)]), metadata=svc)
        assert (ack.accepted, ack.duplicates) == (5, 0)
        ack = stub.Ingest(iter([observation(i) for i in range(3, 7)]), metadata=svc)
        assert (ack.accepted, ack.duplicates) == (2, 2)
        streamed = list(stub.Stream(ahdt_pb2.StreamRequest(hdt_id=HDT, codes=["8310-5"]),
                                    metadata=svc))
        assert len(streamed) == 7 and streamed[0].number == pytest.approx(38.0)
        person = [("authorization", "Bearer " + issuer.issue("p", Role.PERSON, hdt_id=HDT))]
        with pytest.raises(grpc.RpcError) as err:
            stub.Ingest(iter([observation(9)]), metadata=person)
        assert err.value.code() == grpc.StatusCode.PERMISSION_DENIED
        infer = ahdt_pb2_grpc.InferenceServiceStub(ch).Infer(
            ahdt_pb2.InferRequest(model_id="ahdt.renal_urinary.kidney_and_renal_function",
                                  hdt_id=HDT), metadata=svc)
        assert infer.output_id.startswith("out-")
        assert "creatinine" in infer.values
        with pytest.raises(grpc.RpcError) as missing:
            ahdt_pb2_grpc.InferenceServiceStub(ch).Infer(
                ahdt_pb2.InferRequest(model_id="ahdt.none.model", hdt_id=HDT), metadata=svc)
        assert missing.value.code() == grpc.StatusCode.NOT_FOUND
