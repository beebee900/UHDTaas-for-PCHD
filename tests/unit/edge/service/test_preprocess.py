"""Edge pre-processing on the `edge/devices/sim` ECG trace (design 04, 4.2.1 tier 2)."""

from datetime import timedelta

import numpy as np
import pytest

from edge.devices.decode.observations import FIELD_SYSTEM, HEART_RATE, SPO2
from edge.devices.sim.mqtt import ECG_FS, ecg_trace
from edge.preprocess import ECG_CODE, LOINC, Preprocessor, ecg_strip, is_dropout
from tests.unit.edge.service.support import HDT, START


def reading(code, value, unit, t, system=LOINC):
    return {"code": {"system": system, "code": code, "display": None}, "alt_codes": [],
            "value": value, "unit": unit, "effective_time": t.isoformat(), "hdt_id": HDT,
            "device_id": "dev-1", "source": "device", "sim_time": None}


def ecg(hr, seconds=10.0, noise=0.0, seed=0):
    x = ecg_trace(hr, seconds, ECG_FS)
    if noise:
        x = x + np.random.default_rng(seed).normal(0, noise, x.size)
        x = x + 0.3 * np.sin(2 * np.pi * 0.2 * np.arange(x.size) / ECG_FS)
    return reading(ECG_CODE, {"array": x.tolist(), "period_ms": 1000.0 / ECG_FS}, "mV", START,
                   system="urn:iso:std:iso:11073:10101")


def baseline(x):
    moving = np.convolve(np.asarray(x), np.ones(250) / 250, mode="valid")[250:-250]
    return float(moving.std())


@pytest.mark.parametrize("hr", [55.0, 72.0, 130.0])
def test_r_peaks_of_the_simulated_trace_give_its_heart_rate(hr):
    x = ecg_trace(hr, 10.0, ECG_FS)
    strip = ecg_strip(x, ECG_FS)
    assert strip.heart_rate == pytest.approx(hr, rel=0.02)
    assert strip.rmssd == pytest.approx(0.0, abs=8.0)
    assert len(strip.cleaned) == len(x)


def test_ecg_payload_is_filtered_and_adds_heart_rate_and_rmssd():
    out = Preprocessor().process([ecg(72.0, noise=0.05)], START)
    wave, hr, rmssd = out.payloads
    raw = ecg(72.0, noise=0.05)["value"]["array"]
    assert wave["value"]["period_ms"] == 4.0 and len(wave["value"]["array"]) == len(raw)
    # The band-pass removes the 0.2 Hz baseline wander that a 1 s moving mean follows.
    assert baseline(wave["value"]["array"]) < 0.25 * baseline(raw)
    assert hr["code"]["code"] == HEART_RATE and hr["source"] == "derived"
    assert hr["value"] == pytest.approx(72.0, rel=0.03) and hr["unit"] == "/min"
    assert rmssd["code"] == {"system": FIELD_SYSTEM, "code": "hrv_rmssd", "display": None}


def test_a_flat_strip_gives_no_derived_rate():
    flat = reading(ECG_CODE, {"array": [0.0] * 2500, "period_ms": 4.0}, "mV", START)
    out = Preprocessor().process([flat], START)
    assert [p["code"]["code"] for p in out.payloads] == [ECG_CODE]


def test_spo2_dropouts_are_removed_by_the_plausibility_bounds():
    good = reading(SPO2, 96, "%", START)
    assert not is_dropout(good)
    assert all(is_dropout(reading(SPO2, v, "%", START)) for v in (0, 127, float("nan")))
    out = Preprocessor().process([good, reading(SPO2, 0, "%", START),
                                  reading(SPO2, 127, "%", START)], START)
    assert out.dropouts == 2 and out.payloads == [good]


def test_feature_windows_close_once_across_batches():
    pre = Preprocessor(window_s=60.0)
    first = pre.process([reading(SPO2, 95, "%", START + timedelta(seconds=s))
                         for s in (0, 20)], START + timedelta(seconds=30))
    assert first.features == []
    second = pre.process([reading(SPO2, 92, "%", START + timedelta(seconds=40)),
                          reading(SPO2, 97, "%", START + timedelta(seconds=70))],
                         START + timedelta(seconds=90))
    (window,) = second.features
    assert (window.start, window.n, window.min, window.max) == (START, 3, 92, 95)
    assert window.mean == pytest.approx(94.0)
    assert window.payload()["source"] == "derived" and window.payload()["value"] == 94.0
    (rest,) = pre.process([], START + timedelta(seconds=120)).features
    assert rest.n == 1 and rest.payload() == reading(SPO2, 97, "%",
                                                      START + timedelta(seconds=70))
