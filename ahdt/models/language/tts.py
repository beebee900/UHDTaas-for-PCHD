"""Text to speech with MMS-TTS voices (VITS), one per locale.

Voices: `mms-tts-yor`, `mms-tts-hau`, `mms-tts-eng` (English and Pidgin), and `mms-tts-ibo-ft`,
the Igbo voice fine-tuned from `mms-tts-yor` on the WaxalNLP Igbo TTS corpus (WP14d). The
Yoruba vocabulary has no `ị`, `ụ` or `ṅ`, so Igbo text is mapped to the nearest letters
(`igbo_charset`) before synthesis. Web apps use the browser speech API for English; the server
voice serves tests and phone channels. All MMS-TTS models are CC BY-NC 4.0.
"""

from __future__ import annotations

import asyncio
import re
import threading
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
from numpy.typing import NDArray

from ahdt.models.language.audio import WAV, encode_wav
from ahdt.models.language.locales import DEFAULT_LOCALE, locale_for
from atra.config import ROOT

MODELS_DIR = ROOT / "var" / "models" / "language"
DOT_BELOW_IU = re.compile("([iuIU])\u0323")
DOT_ABOVE_N = re.compile("([nN])\u0307")


def igbo_charset(text: str) -> str:
    """Igbo text in the letters of the Yoruba MMS vocabulary: `ị`, `ụ`, `ṅ` become i, u, n."""
    decomposed = unicodedata.normalize("NFD", text)
    decomposed = DOT_ABOVE_N.sub(r"\1", DOT_BELOW_IU.sub(r"\1", decomposed))
    return unicodedata.normalize("NFC", decomposed)


class MmsTts:
    def __init__(self, model_dir: str | Path, *, igbo: bool = False, threads: int = 2,
                 seed: int = 0) -> None:
        self.model_dir, self.igbo, self.threads, self.seed = str(model_dir), igbo, threads, seed
        self._model: Any = None
        self._tok: Any = None
        self._lock = threading.Lock()

    @property
    def sampling_rate(self) -> int:
        self._load()
        return int(self._model.config.sampling_rate)

    def _load(self) -> None:
        if self._model is None:
            import torch
            from transformers import AutoTokenizer, VitsModel

            torch.set_num_threads(self.threads)
            self._tok = AutoTokenizer.from_pretrained(self.model_dir)
            self._model = VitsModel.from_pretrained(self.model_dir).eval()

    def samples(self, text: str) -> NDArray[np.float32]:
        import torch

        with self._lock:
            self._load()
            if self.igbo:
                text = igbo_charset(text)
            inputs = self._tok(text.lower(), return_tensors="pt")
            torch.manual_seed(self.seed)
            with torch.no_grad():
                wave = self._model(**inputs).waveform[0]
            return np.asarray(wave.cpu().numpy(), dtype=np.float32)

    def synthesize_sync(self, text: str) -> tuple[bytes, str]:
        return encode_wav(self.samples(text), self.sampling_rate), WAV


class TextToSpeech:
    """Voice per locale; matches `synthesize` of Dyon's `VoiceProvider`."""

    def __init__(self, voices: dict[str, MmsTts], *, locale: str = DEFAULT_LOCALE) -> None:
        self.voices, self.locale = voices, locale_for(locale).code

    @classmethod
    def from_dir(cls, root: Path = MODELS_DIR, *, locale: str = DEFAULT_LOCALE) -> TextToSpeech:
        voices = {p.name: MmsTts(p, igbo=p.name == "mms-tts-ibo-ft")
                  for p in root.glob("mms-tts-*") if (p / "config.json").is_file()}
        return cls(voices, locale=locale)

    def voice(self, locale: str | None = None) -> MmsTts:
        key = locale_for(locale or self.locale).tts
        try:
            return self.voices[key]
        except KeyError:
            raise FileNotFoundError(f"voice {key} is not installed") from None

    async def synthesize(self, text: str, locale: str | None = None) -> tuple[bytes, str]:
        return await asyncio.to_thread(self.voice(locale).synthesize_sync, text)

    def for_locale(self, locale: str) -> TextToSpeech:
        return TextToSpeech(self.voices, locale=locale)
