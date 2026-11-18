"""Audio helpers, the speech-to-text router and the MMS-TTS host."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from ahdt.models.language.audio import SAMPLE_RATE, decode, encode_wav, resample
from ahdt.models.language.stt import SpeechToText
from ahdt.models.language.tts import MmsTts, TextToSpeech, igbo_charset


def tone(seconds: float = 0.5, rate: int = SAMPLE_RATE) -> np.ndarray:
    t = np.arange(int(seconds * rate)) / rate
    return (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)


def test_wav_round_trip_and_resampling() -> None:
    wav = encode_wav(tone(0.5, 22_050), 22_050)
    back = decode(wav, "audio/wav")
    assert back.dtype == np.float32 and abs(len(back) - 8000) <= 2
    assert np.abs(back).max() == pytest.approx(0.3, abs=0.01)
    assert resample(back, SAMPLE_RATE, SAMPLE_RATE) is not None


def test_undecodable_audio_is_a_value_error() -> None:
    with pytest.raises(ValueError, match="cannot decode"):
        decode(b"not audio", "audio/mpeg")


class FakeWhisper:
    def __init__(self) -> None:
        self.calls: list[tuple[int, str | None]] = []

    def transcribe_array(self, audio: Any, language: str | None) -> str:
        self.calls.append((len(audio), language))
        return "whisper"


class FakeMms:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def transcribe_array(self, audio: Any, code: str) -> str:
        self.calls.append(code)
        return "mms:" + code


async def test_router_sends_each_locale_to_the_right_model() -> None:
    whisper, mms = FakeWhisper(), FakeMms()
    stt = SpeechToText(whisper, mms)  # type: ignore[arg-type]
    wav = encode_wav(tone(), SAMPLE_RATE)
    assert await stt.transcribe(wav, "audio/wav") == "whisper"
    assert await stt.transcribe(wav, "audio/wav", "pcm") == "whisper"
    assert [await stt.transcribe(wav, "audio/wav", c) for c in ("yo", "ha", "ig")] == [
        "mms:yor", "mms:hau", "mms:ibo"]
    assert whisper.calls == [(8000, "en"), (8000, "en")] and mms.calls == ["yor", "hau", "ibo"]
    assert await stt.for_locale("ig").transcribe(wav) == "mms:ibo"


async def test_missing_models_are_reported() -> None:
    wav = encode_wav(tone(), SAMPLE_RATE)
    with pytest.raises(FileNotFoundError, match="Whisper"):
        await SpeechToText().transcribe(wav, "audio/wav", "en")
    with pytest.raises(FileNotFoundError, match="MMS"):
        await SpeechToText().transcribe(wav, "audio/wav", "yo")


def test_igbo_text_is_mapped_to_the_yoruba_character_set() -> None:
    assert igbo_charset("Kedu ka ị mere? Ụlọ ṅụọ ọ dị mma") == "Kedu ka i mere? Ulọ nuọ ọ di mma"
    assert igbo_charset("Ịkpọ") == "Ikpọ"


def tiny_voice(path: Path) -> None:
    import torch
    from transformers import VitsConfig, VitsModel

    chars = ["|", *"abdeiklmnoprstu '"]
    path.mkdir(parents=True)
    (path / "vocab.json").write_text(json.dumps({c: i for i, c in enumerate(chars)}))
    (path / "tokenizer_config.json").write_text(json.dumps({
        "tokenizer_class": "VitsTokenizer", "pad_token": "|", "unk_token": None,
        "language": None, "add_blank": True, "normalize": True, "phonemize": False,
        "is_uroman": False}))
    cfg = VitsConfig(vocab_size=len(chars), hidden_size=16, num_hidden_layers=1,
                     num_attention_heads=2, ffn_dim=16, flow_size=16, spectrogram_bins=33,
                     upsample_initial_channel=16, upsample_rates=[2, 2],
                     upsample_kernel_sizes=[4, 4], resblock_kernel_sizes=[3],
                     resblock_dilation_sizes=[[1, 3]], depth_separable_num_layers=1,
                     duration_predictor_filter_channels=16, prior_encoder_num_flows=1,
                     prior_encoder_num_wavenet_layers=1, posterior_encoder_num_wavenet_layers=1,
                     wavenet_kernel_size=3, window_size=2, sampling_rate=16000)
    torch.manual_seed(0)
    VitsModel(cfg).save_pretrained(path)


@pytest.fixture(scope="module")
def voice_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    path = tmp_path_factory.mktemp("voices") / "mms-tts-ibo-ft"
    tiny_voice(path)
    return path


def test_tts_returns_deterministic_wav(voice_dir: Path) -> None:
    voice = MmsTts(voice_dir, igbo=True, threads=1)
    wav, ctype = voice.synthesize_sync("Kedu ka ị mere")
    again, _ = voice.synthesize_sync("Kedu ka ị mere")
    assert ctype == "audio/wav" and wav == again
    assert decode(wav).size > 100 and voice.sampling_rate == 16000


async def test_tts_router_picks_the_voice_of_the_locale(voice_dir: Path) -> None:
    tts = TextToSpeech.from_dir(voice_dir.parent)
    assert set(tts.voices) == {"mms-tts-ibo-ft"}
    wav, _ = await tts.synthesize("Kedu ka ị mere", "ig")
    assert wav[:4] == b"RIFF"
    with pytest.raises(FileNotFoundError, match="mms-tts-yor"):
        await tts.synthesize("Báwo ni", "yo")
