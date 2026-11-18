"""The five supported conversation languages and the models that serve each (design 04, 4.5.3).

A locale code is the short form used across ATRA: `en`, `yo`, `ha`, `ig`, `pcm`. The table
names, per locale, the speech models (Whisper language code or MMS adapter code, MMS-TTS
voice), the name used in prompts and the LoRA adapter id.
"""

from __future__ import annotations

from dataclasses import dataclass

DEFAULT_LOCALE = "en"


@dataclass(frozen=True)
class Locale:
    code: str
    name: str
    whisper: str | None
    """Whisper language code; Pidgin has none and is decoded as English."""
    mms_asr: str | None
    """MMS-1b-all adapter code (ISO 639-3); English and Pidgin use Whisper."""
    tts: str
    """Key of the voice in `tts.py`: an MMS-TTS model or a fine-tuned local voice."""
    adapter: str | None
    """LoRA adapter id (`lora-<code>`); English uses the base model."""

    @property
    def local_name(self) -> str:
        return self.name


LOCALES: dict[str, Locale] = {
    "en": Locale("en", "English", "en", None, "mms-tts-eng", None),
    "yo": Locale("yo", "Yoruba", None, "yor", "mms-tts-yor", "lora-yo"),
    "ha": Locale("ha", "Hausa", None, "hau", "mms-tts-hau", "lora-ha"),
    "ig": Locale("ig", "Igbo", None, "ibo", "mms-tts-ibo-ft", "lora-ig"),
    "pcm": Locale("pcm", "Nigerian Pidgin", "en", None, "mms-tts-eng", "lora-pcm"),
}


def locale_for(code: str | None) -> Locale:
    """The locale of `code` (case and region suffix ignored); unknown codes raise ValueError."""
    key = (code or DEFAULT_LOCALE).lower().replace("_", "-").split("-")[0]
    try:
        return LOCALES[key]
    except KeyError:
        raise ValueError(f"unsupported language {code!r}; supported: {', '.join(LOCALES)}") \
            from None
