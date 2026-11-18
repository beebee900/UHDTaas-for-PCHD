"""Voice prompts for the IVR (design 05, 5.3): text-to-speech per language, cached.

A synthesiser has Dyon's `VoiceProvider.synthesize(text) -> (audio, content_type)`. MMS-TTS
(facebook/mms-tts-yor, -hau, -ibo) runs as such a provider on a machine that can host it.
`ToneSynthesiser` is the offline stand-in: a deterministic WAV whose length follows the
text, so the IVR flow runs and is tested without a speech model.
"""

from __future__ import annotations

import hashlib
import io
import math
import struct
import threading
import wave
from collections.abc import Mapping
from typing import Protocol

RATE = 8000


class Synthesiser(Protocol):
    async def synthesize(self, text: str) -> tuple[bytes, str]: ...


class ToneSynthesiser:
    async def synthesize(self, text: str) -> tuple[bytes, str]:
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            frames = bytearray()
            for word in text.split() or [""]:
                pitch = 300 + int(hashlib.sha256(word.encode()).hexdigest()[:2], 16)
                for i in range(int(RATE * 0.12)):
                    frames += struct.pack("<h", int(8000 * math.sin(2 * math.pi * pitch * i
                                                                    / RATE)))
                frames += b"\0\0" * int(RATE * 0.04)
            w.writeframes(bytes(frames))
        return buf.getvalue(), "audio/wav"


class PromptCache:
    """Synthesised prompts by key; the IVR plays them by URL."""

    def __init__(self, voices: Mapping[str, Synthesiser]) -> None:
        self.voices = dict(voices)
        self._audio: dict[str, tuple[bytes, str]] = {}
        self._lock = threading.Lock()

    def has_voice(self, language: str) -> bool:
        return language in self.voices

    async def prompt(self, language: str, text: str) -> str:
        key = hashlib.sha256(f"{language}|{text}".encode()).hexdigest()[:24]
        with self._lock:
            cached = key in self._audio
        if not cached:
            audio = await self.voices[language].synthesize(text)
            with self._lock:
                self._audio[key] = audio
        return key

    def audio(self, key: str) -> tuple[bytes, str] | None:
        with self._lock:
            return self._audio.get(key)
