"""Bandwidth adaptation by link profile (design 04, 4.2.2)."""

from datetime import timedelta

import grpc
import pytest

from edge.bandwidth import POLICIES, Shaper, policy
from edge.devices.decode.observations import SPO2
from edge.outbox import Ack, Outbox
from edge.preprocess import ECG_CODE, Preprocessed
from edge.registry import DeviceCA, DeviceRegistry
from edge.runtime import EdgeRuntime
from edge.uplink import GrpcIngestor
from tests.unit.edge.service.support import START
from tests.unit.edge.service.test_preprocess import reading


def batch(*seconds, ecg=True):
    payloads = [reading(SPO2, 95 + i % 3, "%", START + timedelta(seconds=s))
                for i, s in enumerate(seconds)]
    if ecg:
        payloads.append(reading(ECG_CODE, {"array": [0.0] * 10, "period_ms": 4.0}, "mV",
                                START))
    payloads.append(reading("text-note", "fine", "1", START))
    return Preprocessed(payloads=payloads)


def test_profiles():
    assert set(POLICIES) == {"wifi", "4g", "2g", "offline"}
    two_g = policy("2g")
    assert (two_g.waveforms, two_g.windowed, two_g.batch_size, two_g.compression) == (
        False, True, 100, grpc.Compression.Gzip)
    offline = policy("offline")
    assert not offline.deliver and offline.sms_alerts and offline.waveforms
    assert all(policy(p).deliver and not policy(p).sms_alerts for p in ("wifi", "4g"))
    with pytest.raises(ValueError, match="unknown link profile"):
        policy("5g")


@pytest.mark.parametrize("profile", ["wifi", "4g", "offline"])
def test_full_profiles_send_every_reading(profile):
    b = batch(0, 10)
    assert Shaper(profile).select(b, START) == b.payloads


def test_2g_sends_window_means_instead_of_raw_streams_and_no_waveforms():
    shaper = Shaper("2g", window_s=60.0)
    first = shaper.select(batch(0, 10, 20), START + timedelta(seconds=30))
    assert [p["code"]["code"] for p in first] == ["text-note"]
    second = shaper.select(batch(70, ecg=False), START + timedelta(seconds=90))
    assert [p["code"]["code"] for p in second] == ["text-note", SPO2]
    assert second[1]["value"] == pytest.approx(96.0) and second[1]["source"] == "derived"
    # Leaving 2g releases the open window at once, so the reading at 70 s is not held back.
    (released,) = shaper.set_link("wifi")
    assert released["effective_time"] == (START + timedelta(seconds=70)).isoformat()
    assert shaper.set_link("2g") == [] and shaper.flush() == []


class Counting:
    def __init__(self):
        self.calls = []

    async def ingest(self, observations):
        self.calls.append(len(observations))
        return Ack(len(observations), 0, 0)


def edge(edge_settings, ingestor, profile):
    return EdgeRuntime(edge_settings.model_copy(update={"link": profile}),
                       registry=DeviceRegistry(None, DeviceCA.generate()),
                       outbox=Outbox(None), ingestor=ingestor, clock=lambda: START)


async def test_offline_buffers_and_delivery_uses_the_profile_batch_size(edge_settings):
    link = Counting()
    rt = edge(edge_settings, link, "offline")
    rt.outbox.enqueue([reading(SPO2, 90 + i % 9, "%", START + timedelta(seconds=i))
                       for i in range(250)])
    result = await rt.deliver()
    assert result.link_down and link.calls == [] and rt.outbox.counts()["pending"] == 250
    rt.set_link("2g")
    result = await rt.deliver()
    assert link.calls == [100, 100, 50] and result.accepted == 250
    assert rt.outbox.counts() == {"pending": 0, "acked": 250, "rejected": 0}


async def test_2g_sets_gzip_on_the_grpc_stream(edge_settings):
    ingestor = GrpcIngestor("127.0.0.1:1", lambda: "token")
    rt = edge(edge_settings, ingestor, "2g")
    await rt.deliver()
    assert ingestor.compression == grpc.Compression.Gzip
    rt.set_link("wifi")
    await rt.deliver()
    assert ingestor.compression == grpc.Compression.NoCompression
