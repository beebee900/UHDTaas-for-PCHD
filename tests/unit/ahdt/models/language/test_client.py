"""Chat backends: hosted request, token accounting, timeouts, fallback chain."""

from __future__ import annotations

import httpx
import pytest
from pydantic import SecretStr

from ahdt.models.language.client import (
    BackendUnavailable,
    ChatChain,
    KeyPool,
    OfflineBackend,
    OllamaBackend,
    OpenAIBackend,
    SlmBackend,
)
from ahdt.models.language.usage import UsageLedger
from atra.config import LLMSettings
from tests.unit.ahdt.models.language.fakes import FakeOllama, FakeSLM

MESSAGES = [{"role": "system", "content": "x Reply in Yoruba in one or two"},
            {"role": "user", "content": "hello"}]


def settings(*keys: str, provider: str = "ollama") -> LLMSettings:
    return LLMSettings(provider=provider, base_url="http://ollama.test",  # type: ignore[arg-type]
                       api_keys=[SecretStr(k) for k in keys or ("secret",)], timeout_s=5.0)


async def test_hosted_call_sends_bearer_key_and_reports_tokens() -> None:
    server = FakeOllama()
    backend = OllamaBackend(settings(), client=server.client())
    done = await backend.chat(MESSAGES, max_tokens=50, timeout_s=10, locale="yo")
    assert done.text == "[Yoruba] ok" and done.backend == "ollama"
    assert (done.usage.prompt_tokens, done.usage.completion_tokens) == (21, 4)
    assert not done.usage.estimated
    assert server.headers[0]["authorization"] == "Bearer secret"
    assert server.requests[0]["options"]["num_predict"] == 50
    assert server.requests[0]["stream"] is False


async def test_no_key_sends_no_authorization_header() -> None:
    server = FakeOllama()
    keyless = LLMSettings(base_url="http://ollama.test", timeout_s=5.0)
    await OllamaBackend(keyless, client=server.client()).chat(
        MESSAGES, max_tokens=10, timeout_s=10)
    assert "authorization" not in server.headers[0]


async def test_http_error_and_timeout_raise_backend_unavailable() -> None:
    down = OllamaBackend(settings(), client=FakeOllama(status=503).client())
    with pytest.raises(BackendUnavailable, match="503"):
        await down.chat(MESSAGES, max_tokens=10, timeout_s=10)
    slow = OllamaBackend(settings(), client=FakeOllama(delay_s=1.0).client())
    with pytest.raises(BackendUnavailable):
        await slow.chat(MESSAGES, max_tokens=10, timeout_s=0.05)


async def test_a_rate_limited_key_hands_the_call_to_the_next_key() -> None:
    server = FakeOllama(refuse={"k1": 429})
    backend = OllamaBackend(settings("k1", "k2"), client=server.client())
    done = await backend.chat(MESSAGES, max_tokens=10, timeout_s=10)
    assert done.text == "[Yoruba] ok"
    assert [h["authorization"] for h in server.headers] == ["Bearer k1", "Bearer k2"]
    await backend.chat(MESSAGES, max_tokens=10, timeout_s=10)
    assert server.headers[-1]["authorization"] == "Bearer k2"


def test_a_resting_key_is_tried_last() -> None:
    now = [0.0]
    pool = KeyPool(["a", "b", "c"], rest_s=60, clock=lambda: now[0])
    pool.refused(0)
    assert pool.order() == [1, 2, 0]
    now[0] = 61.0
    assert pool.order() == [0, 1, 2]


async def test_every_key_refused_is_unavailable() -> None:
    server = FakeOllama(refuse={"k1": 401, "k2": 429})
    backend = OllamaBackend(settings("k1", "k2"), client=server.client())
    with pytest.raises(BackendUnavailable, match="no key could answer"):
        await backend.chat(MESSAGES, max_tokens=10, timeout_s=10)


async def test_openai_compatible_backend_reads_choices_and_usage() -> None:
    server = FakeOllama()
    done = await OpenAIBackend(settings("g1", provider="openai"), client=server.client()).chat(
        MESSAGES, max_tokens=30, timeout_s=10)
    assert (done.text, done.backend) == ("ok", "openai")
    assert (done.usage.prompt_tokens, done.usage.completion_tokens) == (12, 1)
    assert server.requests[0]["max_tokens"] == 30
    assert server.headers[0]["authorization"] == "Bearer g1"


async def test_connection_failure_is_unavailable() -> None:
    transport = httpx.MockTransport(lambda r: (_ for _ in ()).throw(httpx.ConnectError("no route")))
    backend = OllamaBackend(settings(), client=httpx.AsyncClient(transport=transport))
    with pytest.raises(BackendUnavailable, match="ConnectError"):
        await backend.chat(MESSAGES, max_tokens=10, timeout_s=1)


async def test_local_model_counts_tokens_and_names_the_adapter() -> None:
    done = await SlmBackend(FakeSLM("lora-yo")).chat(MESSAGES, max_tokens=20, timeout_s=5)
    assert done.text == "local:lora-yo" and done.adapter == "lora-yo"
    assert done.usage.prompt_tokens == 9 and not done.usage.estimated


async def test_offline_backend_is_deterministic_and_says_it_is_offline() -> None:
    backend = OfflineBackend()
    a = await backend.chat(MESSAGES, max_tokens=20, timeout_s=5)
    b = await backend.chat(MESSAGES, max_tokens=20, timeout_s=5)
    assert a.text == b.text and a.text.startswith("[offline model]")
    assert a.usage.estimated and a.backend == "offline"


async def test_offline_backend_takes_a_responder() -> None:
    done = await OfflineBackend(lambda prompt: "ok:" + prompt[-5:]).chat(
        MESSAGES, max_tokens=5, timeout_s=1)
    assert done.text == "ok:hello"


async def test_chain_falls_through_failures_and_records_every_attempt() -> None:
    ledger = UsageLedger()
    chain = ChatChain([OllamaBackend(settings(), client=FakeOllama(status=500).client()),
                       SlmBackend(FakeSLM("lora-ha")), OfflineBackend()], ledger)
    done, failures = await chain.chat(MESSAGES, max_tokens=10, timeout_s=5, locale="ha")
    assert done.backend == "slm" and len(failures) == 1 and "500" in failures[0]
    totals = ledger.totals()
    assert totals["ollama"]["failures"] == 1 and totals["slm"]["calls"] == 1
    assert totals["slm"]["completion_tokens"] == 1


async def test_chain_without_a_working_backend_raises() -> None:
    chain = ChatChain([OllamaBackend(settings(), client=FakeOllama(status=500).client())])
    with pytest.raises(BackendUnavailable):
        await chain.chat(MESSAGES, max_tokens=10, timeout_s=5)
    with pytest.raises(ValueError, match="at least one"):
        ChatChain([])
