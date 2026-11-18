"""NFR6: the edge-to-AHDT link is cut for 30 simulated minutes; after reconnection every
reading arrives in the AHDT once (design 07, 7.7; design 09 NFR6).

The oximeter sends a frame every 5 simulated seconds and the edge steps every 5 simulated
minutes, so the hour runs in a few wall-clock seconds."""

from datetime import timedelta

from starlette.testclient import TestClient

from ahdt.app import build_app as build_ahdt
from atra.config import AHDTSettings
from edge.outbox import LinkDown, Outbox
from edge.registry import DeviceCA, DeviceRegistry
from edge.runtime import EdgeRuntime
from edge.uplink import GrpcIngestor
from tests.unit.edge.service.support import HDT, oximeter_frame

SPO2, HR = "59408-5", "8867-4"


class Link:
    """The edge-to-cloud link as a fault injector: cut, or deliver and lose the ack."""

    def __init__(self, inner):
        self.inner = inner
        self.cut = False
        self.lose_next_ack = False
        self.calls = 0

    async def ingest(self, observations):
        self.calls += 1
        if self.cut:
            raise LinkDown("link cut")
        ack = await self.inner.ingest(observations)
        if self.lose_next_ack:
            self.lose_next_ack = False
            raise LinkDown("acknowledgement lost")
        return ack


async def test_thirty_minute_link_cut_loses_and_duplicates_nothing(
        settings, backends, clock, edge_settings, tmp_path):
    ahdt = build_ahdt(settings.model_copy(update={"ahdt": AHDTSettings(grpc_port=0)}),
                      backends=backends("ahdt"))
    issuer = ahdt.state.backends.issuer
    with TestClient(ahdt) as client:
        grpc_client = GrpcIngestor(f"127.0.0.1:{ahdt.state.grpc_port}",
                                   lambda: issuer.issue_service("edge-svc"))
        link = Link(grpc_client)
        outbox_path = tmp_path / "outbox.sqlite"
        edge = EdgeRuntime(edge_settings, registry=DeviceRegistry(None, DeviceCA.generate()),
                           outbox=Outbox(outbox_path, clock=clock.now), ingestor=link,
                           clock=clock.now)
        edge.registry.register("po-1", "pulse_oximeter", HDT)
        broker = edge.transports.mqtt

        sent: list = []
        for frame, second in enumerate(range(0, 60 * 60, 5), start=1):
            if second == 10 * 60:
                link.cut = True
            if second == 40 * 60:
                link.cut = False
                link.lose_next_ack = True
                # QoS 1 redelivery after the reconnect: the last three frames again, DUP set.
                for t, spo2, pulse, pid in sent[-3:]:
                    oximeter_frame(broker, "po-1", t, spo2, pulse, packet_id=pid, dup=True)
            t = clock.now()
            spo2, pulse = 95 + (frame - 1) % 4, 68 + (frame - 1) % 7
            oximeter_frame(broker, "po-1", t, spo2, pulse, packet_id=frame % 65535 + 1)
            sent.append((t, spo2, pulse, frame % 65535 + 1))
            clock.advance(5)
            if second % 300 == 295:
                result = await edge.step()
                if 10 * 60 <= second < 40 * 60:
                    assert not result.cloud_reachable
        # The outbox is a file: a restart of the edge during the cut keeps the backlog.
        assert edge.outbox.counts()["pending"] == 0
        restarted = Outbox(outbox_path, clock=clock.now)
        assert restarted.counts() == edge.outbox.counts()
        await grpc_client.close()

        stored = {code: client.portal.call(ahdt.state.backends.timeseries.query, HDT, code)
                  for code in (SPO2, HR)}

    assert len(sent) == 720
    for code, points in stored.items():
        times = [p.t for p in points]
        assert len(points) == 720, code
        assert len(set(times)) == 720, code
        assert times[0] == sent[0][0] and times[-1] == sent[-1][0]
    assert [p.v for p in stored[SPO2]] == [s for _, s, _, _ in sent]
    counts = edge.outbox.counts()
    assert counts == {"pending": 0, "acked": 1440, "rejected": 0}
    assert link.calls > 1


async def test_lost_acknowledgement_is_counted_as_duplicates(settings, backends, clock,
                                                             edge_settings):
    ahdt = build_ahdt(settings.model_copy(update={"ahdt": AHDTSettings(grpc_port=0)}),
                      backends=backends("ahdt"))
    issuer = ahdt.state.backends.issuer
    with TestClient(ahdt):
        grpc_client = GrpcIngestor(f"127.0.0.1:{ahdt.state.grpc_port}",
                                   lambda: issuer.issue_service("edge-svc"))
        link = Link(grpc_client)
        edge = EdgeRuntime(edge_settings, registry=DeviceRegistry(None, DeviceCA.generate()),
                           outbox=Outbox(None, clock=clock.now), ingestor=link,
                           clock=clock.now)
        edge.registry.register("po-1", "pulse_oximeter", HDT)
        for i in range(10):
            oximeter_frame(edge.transports.mqtt, "po-1", clock.now() + timedelta(seconds=i),
                           96, 70, packet_id=i + 1)
        link.lose_next_ack = True
        first = await edge.step()
        second = await edge.step()
        await grpc_client.close()
    assert first.drain.link_down and first.drain.sent == 0
    assert (second.drain.sent, second.drain.accepted, second.drain.duplicates) == (20, 0, 20)
