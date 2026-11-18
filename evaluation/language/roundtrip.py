"""STT and TTS round trip: text to speech to text, one clip of about 10 seconds per language.

    python -m evaluation.language.roundtrip

For each locale the script takes the held-out replies of the language (Yoruba, Hausa and Igbo
from the NLLB translations, English and Pidgin from the templates), joins sentences until the
synthesised audio lasts at least 10 seconds, writes the WAV, transcribes it, and reports word
error rate and chrF against the input text. Voices are MMS-TTS (`mms-tts-yor`, `mms-tts-hau`,
the fine-tuned `mms-tts-ibo-ft`, `mms-tts-eng` for English and Pidgin); STT is faster-whisper
small for English and Pidgin and MMS-1b-all adapters for yo, ha, ig. Pidgin has no voice of its
own and no Whisper language: English models read and hear it, so its error rates are expected
to be worse. Output: `$ATRA/out/wp14d/eval/roundtrip.json` and the clips.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from ahdt.models.language.audio import encode_wav
from ahdt.models.language.locales import LOCALES
from ahdt.models.language.stt import FasterWhisperSTT, MmsAsr, SpeechToText
from ahdt.models.language.tts import MmsTts
from evaluation.language import common
from evaluation.language.metrics import chrf, wer

TARGET_SECONDS = 10.0
MAX_SENTENCES = 6


def sentences(lang: str) -> list[str]:
    dialogues = common.read_jsonl(common.HERE / "data" / "dialogues_en.jsonl")
    if lang == "en":
        return [t["en"] for d in dialogues for t in d["turns"] if t["role"] == "assistant"]
    if lang == "pcm":
        return [t["pcm"] for d in dialogues for t in d["turns"] if t["role"] == "assistant"]
    tr = json.loads((common.DATA / "translations.json").read_text("utf-8"))[lang]
    return [tr[t["en"]] for d in dialogues for t in d["turns"] if t["role"] == "assistant"]


def pick_text(voice: MmsTts, candidates: list[str]) -> str:
    """Sentences of 6 to 25 words in sorted order, joined until the clip reaches the target."""
    pool = [t for t in sorted(set(candidates)) if 6 <= len(t.split()) <= 25]
    chosen: list[str] = []
    for text in pool:
        chosen.append(text)
        if len(voice.samples(" ".join(chosen))) / voice.sampling_rate >= TARGET_SECONDS \
                or len(chosen) >= MAX_SENTENCES:
            break
    return " ".join(chosen)


def main() -> int:
    voices = {key: MmsTts(common.MODELS / key, igbo=key == "mms-tts-ibo-ft")
              for key in {loc.tts for loc in LOCALES.values()}}
    voices["mms-tts-ibo-ft"] = MmsTts(common.OUT / "mms-tts-ibo-ft" / "model", igbo=True)
    stt = SpeechToText(FasterWhisperSTT(common.MODELS / "whisper-small"),
                       MmsAsr(common.MODELS / "mms-asr"))
    clips = common.OUT / "eval" / "clips"
    clips.mkdir(parents=True, exist_ok=True)
    result: dict[str, dict[str, object]] = {}
    for code, loc in LOCALES.items():
        voice = voices[loc.tts]
        text = pick_text(voice, sentences(code))
        wave = voice.samples(text)
        seconds = len(wave) / voice.sampling_rate
        wav = encode_wav(wave, voice.sampling_rate)
        Path(clips / f"{code}.wav").write_bytes(wav)
        t0 = time.time()
        heard = stt.transcribe_sync(wav, "audio/wav", code)
        result[code] = {"voice": loc.tts, "seconds": round(seconds, 1), "text": text,
                        "transcript": heard, "wer": wer(heard, text),
                        "chrf": chrf([heard], [text]), "stt_seconds": round(time.time() - t0, 1)}
        common.log(f"{code}: {seconds:.1f} s, WER {result[code]['wer']:.2f}, "
                   f"chrF {result[code]['chrf']:.1f}")
    common.write_json(common.OUT / "eval" / "roundtrip.json", result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
