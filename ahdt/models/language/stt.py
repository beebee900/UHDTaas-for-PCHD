"""Speech to text: faster-whisper for English and Pidgin, MMS-1b-all adapters for yo, ha, ig.

`SpeechToText.transcribe(audio, content_type, locale=...)` matches the `transcribe` of Dyon's
`VoiceProvider` and of the scribe's `Transcriber` protocol (the locale defaults to the one
given at construction; `for_locale` binds another). Models load on first use.

Whisper has no Pidgin: Pidgin audio is decoded as English, so its word error rate is higher
than English audio (`evaluation/language/`). MMS-1b-all is CC BY-NC 4.0.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from typing import Any

from numpy.typing import NDArray

from ahdt.models.language.audio import SAMPLE_RATE, decode
from ahdt.models.language.locales import DEFAULT_LOCALE, locale_for
from atra.config import ROOT

MODELS_DIR = ROOT / "var" / "models" / "language"


class FasterWhisperSTT:
    """`faster_whisper.WhisperModel` on CPU with int8 weights."""

    def __init__(self, model: str | Path, *, threads: int = 2) -> None:
        self.model_path, self.threads = str(model), threads
        self._model: Any = None
        self._lock = threading.Lock()

    def transcribe_array(self, audio: NDArray[Any], language: str | None) -> str:
        with self._lock:
            if self._model is None:
                from faster_whisper import WhisperModel

                self._model = WhisperModel(self.model_path, device="cpu", compute_type="int8",
                                           cpu_threads=self.threads)
            segments, _ = self._model.transcribe(audio, language=language, beam_size=5)
            return " ".join(s.text.strip() for s in segments).strip()


class MmsAsr:
    """MMS-1b-all with one language adapter loaded at a time."""

    def __init__(self, model_dir: str | Path, *, threads: int = 2) -> None:
        self.model_dir, self.threads = str(model_dir), threads
        self._model: Any = None
        self._processor: Any = None
        self._adapter: str | None = None
        self._lock = threading.Lock()

    def transcribe_array(self, audio: NDArray[Any], code: str) -> str:
        import torch

        with self._lock:
            if self._model is None:
                from transformers import AutoProcessor, Wav2Vec2ForCTC

                torch.set_num_threads(self.threads)
                self._processor = AutoProcessor.from_pretrained(self.model_dir)
                self._model = Wav2Vec2ForCTC.from_pretrained(self.model_dir).eval()
            if self._adapter != code:
                self._processor.tokenizer.set_target_lang(code)
                self._model.load_adapter(code)
                self._adapter = code
            inputs = self._processor(audio, sampling_rate=SAMPLE_RATE, return_tensors="pt")
            with torch.no_grad():
                logits = self._model(**inputs).logits
            ids = torch.argmax(logits, dim=-1)[0]
            return str(self._processor.decode(ids)).strip()


class SpeechToText:
    def __init__(self, whisper: FasterWhisperSTT | None = None, mms: MmsAsr | None = None,
                 *, locale: str = DEFAULT_LOCALE) -> None:
        self.whisper, self.mms, self.locale = whisper, mms, locale_for(locale).code

    @classmethod
    def from_dir(cls, root: Path = MODELS_DIR, *, locale: str = DEFAULT_LOCALE
                 ) -> SpeechToText:
        whisper = root / "faster-whisper-small"
        mms = root / "mms-1b-all"
        return cls(FasterWhisperSTT(whisper) if whisper.is_dir() else None,
                   MmsAsr(mms) if mms.is_dir() else None, locale=locale)

    def transcribe_sync(self, audio: bytes, content_type: str, locale: str | None = None) -> str:
        loc = locale_for(locale or self.locale)
        samples = decode(audio, content_type)
        if loc.mms_asr:
            if self.mms is None:
                raise FileNotFoundError("the MMS speech model is not installed")
            return self.mms.transcribe_array(samples, loc.mms_asr)
        if self.whisper is None:
            raise FileNotFoundError("the Whisper speech model is not installed")
        return self.whisper.transcribe_array(samples, loc.whisper)

    async def transcribe(self, audio: bytes, content_type: str = "audio/wav",
                         locale: str | None = None) -> str:
        return await asyncio.to_thread(self.transcribe_sync, audio, content_type, locale)

    def for_locale(self, locale: str) -> SpeechToText:
        return SpeechToText(self.whisper, self.mms, locale=locale)
