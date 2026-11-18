"""Chat backends for the language service: the hosted model, the local small model, offline.

Every backend answers `chat(messages, max_tokens, timeout_s)` with a `Completion` that carries
the text, the model, the token counts and the latency. `ChatChain` tries the backends in order
and records every attempt in a `UsageLedger`; a backend that raises `BackendUnavailable`
(timeout, HTTP error, missing model) passes the call to the next one. The last backend of a
chain is always `OfflineBackend`, so a chain never fails.

`OllamaBackend` talks to the Ollama `/api/chat` endpoint (Ollama Cloud, or a local server).
`OpenAIBackend` talks to an OpenAI-compatible `/chat/completions` endpoint. Both take the keys
of `LLMSettings.api_keys` through a `KeyPool`: a key that is rate limited or refused rests, and
the next key answers the same call. `SlmBackend` runs an `EdgeSLM` of `edge/slm.py`.
`OfflineBackend` wraps Dyon's `OfflineChatModel`, which states plainly that no model answered.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import FunctionType, MethodType
from typing import Any, Protocol, cast

import httpx

from ahdt.models.language.usage import TokenUsage, UsageLedger, UsageRecord
from atra.config import LLMSettings
from edge.slm import EdgeSLM

type Message = Mapping[str, str]

CHARS_PER_TOKEN = 4


class BackendUnavailable(RuntimeError):
    """The backend could not answer in time or at all."""


@dataclass(frozen=True)
class Completion:
    text: str
    backend: str
    model: str
    usage: TokenUsage
    latency_s: float
    adapter: str | None = None


class ChatBackend(Protocol):
    name: str
    model: str

    async def chat(self, messages: Sequence[Message], *, max_tokens: int, timeout_s: float,
                   locale: str = "en") -> Completion: ...


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / CHARS_PER_TOKEN)) if text else 0


# Status codes that mean "this key cannot answer now"; another key may.
KEY_STATUSES = frozenset({401, 402, 403, 429})


class KeyPool:
    """The API keys of one hosted backend. The current key answers until it is refused."""

    def __init__(self, keys: Sequence[str], *, rest_s: float = 60.0,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self.keys = list(keys)
        self.rest_s = rest_s
        self._clock = clock
        self._current = 0
        self._resting: dict[int, float] = {}

    def order(self) -> list[int]:
        """Key indexes to try: the current key first, then the others; rested keys last."""
        n = len(self.keys)
        ring = [(self._current + i) % n for i in range(n)]
        now = self._clock()
        return ([i for i in ring if self._resting.get(i, 0.0) <= now]
                + [i for i in ring if self._resting.get(i, 0.0) > now])

    def refused(self, index: int) -> None:
        self._resting[index] = self._clock() + self.rest_s

    def answered(self, index: int) -> None:
        self._current = index
        self._resting.pop(index, None)

    def header(self, index: int) -> dict[str, str]:
        # Lowercase key: the Ollama client treats a differently cased header as absent.
        return {"authorization": f"Bearer {self.keys[index]}"}


class _HostedBackend:
    """A hosted chat API behind a `KeyPool`. Subclasses build the request and read the reply."""

    name = "hosted"
    path = ""

    def __init__(self, settings: LLMSettings, *, client: httpx.AsyncClient | None = None,
                 temperature: float = 0.2) -> None:
        self.model = settings.model
        self.base_url = settings.base_url.rstrip("/")
        self.timeout_s = settings.timeout_s
        self.temperature = temperature
        self.keys = KeyPool([k.get_secret_value() for k in settings.api_keys],
                            rest_s=settings.key_rest_s)
        self._client = client

    def body(self, messages: Sequence[Message], max_tokens: int) -> dict[str, Any]:
        raise NotImplementedError

    def read(self, data: Mapping[str, Any]) -> tuple[str, TokenUsage, str]:
        raise NotImplementedError

    async def _post(self, body: dict[str, Any], headers: dict[str, str],
                    timeout: float) -> httpx.Response:
        url = f"{self.base_url}{self.path}"
        if self._client is not None:
            return await self._client.post(url, json=body, headers=headers, timeout=timeout)
        async with httpx.AsyncClient() as client:
            return await client.post(url, json=body, headers=headers, timeout=timeout)

    async def chat(self, messages: Sequence[Message], *, max_tokens: int, timeout_s: float,
                   locale: str = "en") -> Completion:
        body = self.body(messages, max_tokens)
        start = time.monotonic()
        timeout = min(timeout_s, self.timeout_s)
        notes: list[str] = []
        attempts: list[int | None] = list(self.keys.order()) or [None]
        for index in attempts:
            headers = self.keys.header(index) if index is not None else {}
            left = timeout - (time.monotonic() - start)
            if left <= 0:
                break
            try:
                r = await asyncio.wait_for(self._post(body, headers, left), left)
                if index is not None and r.status_code in KEY_STATUSES:
                    self.keys.refused(index)
                    notes.append(f"key {index + 1}: HTTP {r.status_code}")
                    continue
                r.raise_for_status()
                text, usage, model = self.read(r.json())
            except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError,
                    TimeoutError) as exc:
                raise BackendUnavailable(f"{self.name}: {type(exc).__name__}: {exc}") from exc
            if index is not None:
                self.keys.answered(index)
            return Completion(text, self.name, model, usage, time.monotonic() - start)
        raise BackendUnavailable(f"{self.name}: no key could answer ({'; '.join(notes)})")


class OllamaBackend(_HostedBackend):
    """Ollama `/api/chat`, non-streaming. Token counts come from the response."""

    name = "ollama"
    path = "/api/chat"

    def body(self, messages: Sequence[Message], max_tokens: int) -> dict[str, Any]:
        return {"model": self.model, "stream": False, "messages": [dict(m) for m in messages],
                "options": {"num_predict": max_tokens, "temperature": self.temperature}}

    def read(self, data: Mapping[str, Any]) -> tuple[str, TokenUsage, str]:
        usage = TokenUsage(int(data.get("prompt_eval_count") or 0),
                           int(data.get("eval_count") or 0))
        return str(data["message"]["content"]).strip(), usage, str(data.get("model", self.model))


class OpenAIBackend(_HostedBackend):
    """An OpenAI-compatible `/chat/completions` endpoint, non-streaming."""

    name = "openai"
    path = "/chat/completions"

    def body(self, messages: Sequence[Message], max_tokens: int) -> dict[str, Any]:
        return {"model": self.model, "stream": False, "messages": [dict(m) for m in messages],
                "max_tokens": max_tokens, "temperature": self.temperature}

    def read(self, data: Mapping[str, Any]) -> tuple[str, TokenUsage, str]:
        usage = data.get("usage") or {}
        tokens = TokenUsage(int(usage.get("prompt_tokens") or 0),
                            int(usage.get("completion_tokens") or 0))
        text = str(data["choices"][0]["message"]["content"]).strip()
        return text, tokens, str(data.get("model", self.model))


def hosted_backend(settings: LLMSettings, *,
                   client: httpx.AsyncClient | None = None) -> _HostedBackend:
    cls = OpenAIBackend if settings.provider == "openai" else OllamaBackend
    return cls(settings, client=client)


class SlmBackend:
    """The local small model: an `EdgeSLM`, or a factory that picks one per locale."""

    name = "slm"

    def __init__(self, slm: EdgeSLM | Callable[[str], EdgeSLM], *,
                 model: str = "Qwen2.5-0.5B-Instruct") -> None:
        self._slm = slm
        self.model = model

    def _for(self, locale: str) -> EdgeSLM:
        if isinstance(self._slm, FunctionType | MethodType) or not hasattr(self._slm, "chat"):
            return cast("Callable[[str], EdgeSLM]", self._slm)(locale)
        return cast("EdgeSLM", self._slm)

    async def chat(self, messages: Sequence[Message], *, max_tokens: int, timeout_s: float,
                   locale: str = "en") -> Completion:
        slm = self._for(locale)
        start = time.monotonic()
        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(slm.chat, messages, max_tokens=max_tokens), timeout_s)
        except (TimeoutError, FileNotFoundError, ImportError, OSError, RuntimeError) as exc:
            raise BackendUnavailable(f"slm: {type(exc).__name__}: {exc}") from exc
        count = getattr(slm, "count_tokens", None)
        if callable(count):
            prompt = sum(int(count(m["content"])) for m in messages)
            usage = TokenUsage(prompt, int(count(text)))
        else:
            usage = TokenUsage(sum(estimate_tokens(m["content"]) for m in messages),
                               estimate_tokens(text), estimated=True)
        adapter = getattr(slm, "adapter", None)
        return Completion(text, self.name, self.model, usage, time.monotonic() - start,
                          adapter=str(adapter) if adapter else None)


class OfflineBackend:
    """Dyon's `OfflineChatModel`: deterministic, no I/O, and honest about it."""

    name = "offline"
    model = "dyon-offline"

    def __init__(self, responder: Callable[[str], str] | None = None) -> None:
        from dyon.intelligent.offline_llm import OfflineChatModel

        self._model: Any = OfflineChatModel(responder=responder) if responder else \
            OfflineChatModel()

    async def chat(self, messages: Sequence[Message], *, max_tokens: int, timeout_s: float,
                   locale: str = "en") -> Completion:
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

        kinds = {"system": SystemMessage, "assistant": AIMessage}
        lc = [kinds.get(m["role"], HumanMessage)(content=m["content"]) for m in messages]
        start = time.monotonic()
        reply = await self._model.ainvoke(lc)
        text = str(reply.content)
        usage = TokenUsage(sum(estimate_tokens(m["content"]) for m in messages),
                           estimate_tokens(text), estimated=True)
        return Completion(text, self.name, self.model, usage, time.monotonic() - start)


class ChatChain:
    """Try the backends in order; the first that answers wins."""

    def __init__(self, backends: Sequence[ChatBackend], ledger: UsageLedger | None = None) -> None:
        if not backends:
            raise ValueError("a chain needs at least one backend")
        self.backends = list(backends)
        self.ledger = ledger or UsageLedger()

    async def chat(self, messages: Sequence[Message], *, max_tokens: int = 160,
                   timeout_s: float = 30.0, locale: str = "en"
                   ) -> tuple[Completion, list[str]]:
        """The completion and the notes of the backends that failed before it."""
        failures: list[str] = []
        for backend in self.backends:
            start = time.monotonic()
            try:
                done = await backend.chat(messages, max_tokens=max_tokens,
                                          timeout_s=timeout_s, locale=locale)
            except BackendUnavailable as exc:
                failures.append(str(exc))
                self.ledger.add(UsageRecord(backend.name, backend.model, locale, TokenUsage(),
                                            time.monotonic() - start, ok=False))
                continue
            self.ledger.add(UsageRecord(done.backend, done.model, locale, done.usage,
                                        done.latency_s))
            return done, failures
        raise BackendUnavailable("; ".join(failures))
