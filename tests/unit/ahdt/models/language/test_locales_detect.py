"""Locale table and language detection."""

from __future__ import annotations

import pytest

from ahdt.models.language.detect import detect_language
from ahdt.models.language.locales import LOCALES, locale_for

SENTENCES = {
    "en": ["How are you feeling today? Do you have a fever?",
           "Thank you. I have written that in your record.",
           "Please take your medicine every morning and come to the clinic."],
    "pcm": ["Wetin dey happen? Abeg tell me how body dey.",
            "I don write am for your record for your care team.",
            "My body no dey fine, I get headache and wahala to breathe."],
    "yo": ["Báwo ni ara rẹ ṣe ń ṣe lónìí? Ṣé o ní ibà?",
           "Mo ti kọ ọ́ sílẹ̀ fún ẹgbẹ́ ìtọ́jú rẹ.",
           "Jọ̀wọ́ mu oògùn rẹ ní àárọ̀ kí o sì wá sí ilé ìwòsàn."],
    "ha": ["Yaya jikinka yau? Kana da zazzabi?",
           "Na rubuta shi a cikin bayananka don ƙungiyar kula da lafiyarka.",
           "Da fatan za ka sha maganinka kowace safiya."],
    "ig": ["Kedu ka ị mere taa? Ị nwere ahụ ọkụ?",
           "Edebere m ya na ndekọ gị maka ndị na-elekọta gị.",
           "Biko ṅụọ ọgwụ gị n'ụtụtụ ọ bụla."],
}


def test_five_locales_with_models() -> None:
    assert set(LOCALES) == {"en", "yo", "ha", "ig", "pcm"}
    assert LOCALES["yo"].mms_asr == "yor" and LOCALES["ig"].mms_asr == "ibo"
    assert LOCALES["pcm"].whisper == "en" and LOCALES["en"].adapter is None
    assert all(LOCALES[c].adapter == f"lora-{c}" for c in ("yo", "ha", "ig", "pcm"))


@pytest.mark.parametrize(("code", "expected"), [
    ("yo", "yo"), ("YO-NG", "yo"), ("ha_NG", "ha"), (None, "en"), ("pcm", "pcm")])
def test_locale_for_accepts_region_suffix_and_default(code: str | None, expected: str) -> None:
    assert locale_for(code).code == expected


def test_locale_for_rejects_unknown_language() -> None:
    with pytest.raises(ValueError, match="unsupported language"):
        locale_for("fr")


@pytest.mark.parametrize(("code", "text"), [(c, s) for c, ss in SENTENCES.items() for s in ss])
def test_detects_each_language(code: str, text: str) -> None:
    got = detect_language(text)
    assert got.locale == code, got.scores
    assert 0.0 < got.confidence <= 1.0


def test_no_signal_returns_the_default_with_zero_confidence() -> None:
    got = detect_language("12345 ...", default="ha")
    assert (got.locale, got.confidence) == ("ha", 0.0)
