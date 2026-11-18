"""Converse in en, yo, ha, ig and pcm through the offline, local and hosted paths."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from ahdt.models.language.converse import Turn, build_converser, hosted_configured
from atra.config import LLMSettings, Settings
from tests.unit.ahdt.models.language.fakes import FakeOllama, FakeSLMFactory

PROMPTS = {
    "en": "How are you feeling today? Do you have a fever?",
    "yo": "Báwo ni ara rẹ ṣe ń ṣe lónìí? Ṣé o ní ibà?",
    "ha": "Yaya jikinka yau? Kana da zazzabi?",
    "ig": "Kedu ka ị mere taa? Ị nwere ahụ ọkụ?",
    "pcm": "Wetin dey happen? Abeg tell me how body dey.",
}
NAMES = {"en": "English", "yo": "Yoruba", "ha": "Hausa", "ig": "Igbo", "pcm": "Nigerian Pidgin"}


def strict(**llm: object) -> Settings:
    return Settings(residency_mode="strict", llm=LLMSettings(**llm))  # type: ignore[arg-type]


def keyed(url: str = "http://ollama.test") -> Settings:
    return Settings(llm=LLMSettings(base_url=url, api_keys=[SecretStr("k")]))


@pytest.mark.parametrize("code", list(PROMPTS))
async def test_offline_converse_detects_the_language(code: str) -> None:
    converser = build_converser(strict(), local=False,
                                responder=lambda p: "offline:" + p[:110])
    reply = await converser.converse(PROMPTS[code])
    assert reply.locale == code and reply.detected is not None
    assert reply.backend == "offline" and reply.text.startswith("offline:")
    assert NAMES[code] in reply.text


@pytest.mark.parametrize("code", list(PROMPTS))
async def test_local_converse_picks_the_adapter_of_the_locale(code: str) -> None:
    factory = FakeSLMFactory()
    converser = build_converser(strict(), slm=factory)
    reply = await converser.converse("hello", locale=code)
    assert reply.backend == "slm" and reply.detected is None
    assert reply.adapter == (None if code == "en" else f"lora-{code}")
    system = factory.built[code].calls[0][0]["content"]
    assert f"Reply in {NAMES[code]}" in system


@pytest.mark.parametrize("code", list(PROMPTS))
async def test_hosted_converse_in_each_language_reports_tokens(code: str) -> None:
    server = FakeOllama()
    converser = build_converser(keyed(), slm=FakeSLMFactory(), client=server.client())
    reply = await converser.converse(PROMPTS[code], history=[Turn("assistant", "Hello")],
                                     facts=["temperature 38.6 C"])
    assert reply.backend == "ollama" and reply.locale == code
    assert reply.text == f"[{NAMES[code]}] ok"
    assert (reply.usage.prompt_tokens, reply.usage.completion_tokens) == (21, 4)
    sent = server.requests[0]["messages"]
    assert sent[0]["role"] == "system" and "temperature 38.6 C" in sent[0]["content"]
    assert "Do not diagnose" in sent[0]["content"]
    assert [m["role"] for m in sent[1:]] == ["assistant", "user"]
    assert converser.ledger.totals()["ollama"]["prompt_tokens"] == 21


async def test_hosted_failure_falls_back_to_local_then_offline() -> None:
    server = FakeOllama(status=503)
    converser = build_converser(keyed(), slm=FakeSLMFactory(), client=server.client())
    reply = await converser.converse("hello", locale="yo")
    assert reply.backend == "slm" and len(reply.failures) == 1
    no_local = build_converser(keyed(), local=False, client=server.client(),
                               responder=lambda p: "offline")
    reply = await no_local.converse("hello", locale="ha")
    assert reply.backend == "offline" and "503" in reply.failures[0]


def test_hosted_model_is_used_only_when_allowed_and_keyed() -> None:
    assert hosted_configured(keyed())
    assert not hosted_configured(Settings(llm=LLMSettings()))
    assert not hosted_configured(Settings(residency_mode="strict",
                                          llm=LLMSettings(api_keys=[SecretStr("k")])))
    assert not hosted_configured(Settings(llm=LLMSettings(provider="offline",
                                                          api_keys=[SecretStr("k")])))
    assert hosted_configured(Settings(llm=LLMSettings(base_url="http://127.0.0.1:11434")))


async def test_strict_residency_never_calls_the_hosted_model() -> None:
    server = FakeOllama()
    settings = Settings(residency_mode="strict",
                        llm=LLMSettings(base_url="http://ollama.test", api_keys=[SecretStr("k")]))
    reply = await build_converser(settings, slm=FakeSLMFactory(), client=server.client()
                                  ).converse("hi", locale="en")
    assert reply.backend == "slm" and server.requests == []


async def test_unsupported_locale_is_rejected() -> None:
    converser = build_converser(strict(), slm=None)
    with pytest.raises(ValueError, match="unsupported language"):
        await converser.converse("bonjour", locale="fr")
