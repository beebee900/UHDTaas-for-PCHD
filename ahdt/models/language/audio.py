"""Audio bytes to the 16 kHz mono float array that the speech models take, and back to WAV."""

from __future__ import annotations

import io
from math import gcd

import numpy as np
from numpy.typing import NDArray

SAMPLE_RATE = 16_000
WAV = "audio/wav"


def decode(audio: bytes, content_type: str = WAV) -> NDArray[np.float32]:
    """WAV, FLAC or OGG bytes as mono float32 at 16 kHz; other formats raise ValueError."""
    import soundfile as sf

    try:
        data, rate = sf.read(io.BytesIO(audio), dtype="float32", always_2d=True)
    except Exception as exc:  # soundfile raises RuntimeError and LibsndfileError
        raise ValueError(f"cannot decode {content_type} audio: {exc}") from exc
    mono = data.mean(axis=1)
    return resample(mono, rate, SAMPLE_RATE)


def resample(x: NDArray[np.float32], rate: int, target: int) -> NDArray[np.float32]:
    if rate == target:
        return x.astype(np.float32, copy=False)
    from scipy.signal import resample_poly

    g = gcd(rate, target)
    return np.asarray(resample_poly(x, target // g, rate // g), dtype=np.float32)


def encode_wav(samples: NDArray[np.float32], rate: int) -> bytes:
    import soundfile as sf

    buf = io.BytesIO()
    sf.write(buf, np.clip(samples, -1.0, 1.0), rate, format="WAV", subtype="PCM_16")
    return buf.getvalue()
