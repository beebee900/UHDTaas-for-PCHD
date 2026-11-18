from datetime import UTC, datetime

import pytest

from atra import ids
from atra.clock import HLCStamp, HybridLogicalClock, SimClock


def test_uuid7_version_variant_and_order():
    values = [ids.uuid7() for _ in range(2000)]
    assert all(v.version == 7 and v.variant == "specified in RFC 4122" for v in values)
    assert values == sorted(values)
    assert len(set(values)) == len(values)


def test_identifier_formats():
    h = ids.hdt_id_for("NIN-12345678901", b"k")
    assert ids.is_hdt_id(h)
    assert h == ids.hdt_id_for("NIN-12345678901", b"k")
    assert h != ids.hdt_id_for("NIN-12345678901", b"other-key")
    assert ids.episode_id(2026, 42) == "ep-2026-000042"
    assert ids.is_episode_id(ids.episode_id(2026, 42))
    assert ids.OUTPUT_ID_RE.match(ids.new_output_id())
    assert ids.FORK_ID_RE.match(ids.new_fork_id())
    assert ids.instance_id("hdt-0123456789ab", "UBERON:0001264") == "inst-hdt-0123456789ab-0001264"
    with pytest.raises(ValueError):
        ids.episode_id(2026, 1_000_000)


def test_manual_sim_clock():
    start = datetime(2026, 10, 1, tzinfo=UTC)
    clock = SimClock(start=start, manual=True)
    assert clock.sim_time() == 0
    clock.advance(3600)
    assert clock.now() == datetime(2026, 10, 1, 1, tzinfo=UTC)
    assert clock.wall_seconds_for(72 * 3600) == 72 * 3600 / 240
    with pytest.raises(ValueError):
        clock.advance(-1)


def test_hlc_orders_send_before_receive_under_skew():
    a = HybridLogicalClock("a", wall_ms=lambda: 1_000)
    b = HybridLogicalClock("b", wall_ms=lambda: 500)   # b's clock runs 500 ms behind
    sent = a.now()
    received = b.update(str(sent))
    assert received > sent
    assert b.now() > received
    assert HLCStamp.parse(str(received)) == received


def test_hlc_counter_increments_within_one_millisecond():
    c = HybridLogicalClock("n", wall_ms=lambda: 7)
    s1, s2 = c.now(), c.now()
    assert (s1.physical_ms, s1.counter) == (7, 0)
    assert (s2.physical_ms, s2.counter) == (7, 1)
