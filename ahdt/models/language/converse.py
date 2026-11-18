"""Conversation in en, yo, ha, ig and pcm: the language side of `ahdt.cognitive.converse`.

    converser = build_converser(get_settings())
    reply = await converser.converse("Báwo ni ara rẹ?", history=turns, facts=["BP 142/90"])

`converse` detects the language of the message (or takes `locale`), builds the prompt for it
and asks the backend chain: the hosted model first when residency and settings allow it, then
the local small model with the language's LoRA adapter, then the offline model. The `Reply`
names the backend, the adapter, the token counts and every backend that failed first.

Grounding facts (for example values from the twin) go into the system prompt; the caller
decides which facts the patient may hear. Consent, role and audit checks belong to the caller.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import httpx

from ahdt.models.language.client import (
    ChatBackend,
    ChatChain,
    OfflineBackend,
    SlmBackend,
    hosted_backend,
)
from ahdt.models.language.detect import Detection, detect_language
from ahdt.models.language.locales import DEFAULT_LOCALE, Locale, locale_for
from ahdt.models.language.prompts import HOSTED_RULES, system_prompt
from ahdt.models.language.usage import TokenUsage, UsageLedger
from atra.config import Settings, get_settings
from edge.slm import EdgeSLM

OLLAMA_CLOUD = "https://ollama.com"


@dataclass(frozen=True)
class Turn:
    role: str
    """`user` or `assistant`."""
    content: str


@dataclass(frozen=True)
class Reply:
    text: str
    locale: str
    backend: str
    model: str
    usage: TokenUsage
    latency_s: float
    adapter: str | None = None
    detected: Detection | None = None
    failures: list[str] = field(default_factory=list)
    """One note per backend that failed before the one that answered."""


class _HostedPrompt:
    """The hosted backend with its extra rules appended to the system message."""

    def __init__(self, inner: ChatBackend) -> None:
        self.inner, self.name, self.model = inner, inner.name, inner.model

    async def chat(self, messages, *, max_tokens, timeout_s, locale="en"):  # type: ignore[no-untyped-def]
        msgs = [dict(m) for m in messages]
        if msgs and msgs[0]["role"] == "system":
            msgs[0]["content"] = _insert_rules(msgs[0]["content"])
        return await self.inner.chat(msgs, max_tokens=max_tokens, timeout_s=timeout_s,
                                     locale=locale)


def _insert_rules(system: str) -> str:
    head, sep, tail = system.partition("\n")
    return f"{head}\n{HOSTED_RULES}{sep}{tail}" if sep else f"{head}\n{HOSTED_RULES}"


class Converser:
    def __init__(self, chain: ChatChain, *, default_locale: str = DEFAULT_LOCALE) -> None:
        self.chain = chain
        self.default_locale = locale_for(default_locale).code

    @property
    def ledger(self) -> UsageLedger:
        return self.chain.ledger

    def resolve(self, text: str, locale: str | None) -> tuple[Locale, Detection | None]:
        if locale:
            return locale_for(locale), None
        det = detect_language(text, default=self.default_locale)
        return locale_for(det.locale), det

    async def converse(self, text: str, *, locale: str | None = None,
                       history: Sequence[Turn] = (), facts: Sequence[str] = (),
                       max_tokens: int = 160, timeout_s: float = 30.0) -> Reply:
        loc, det = self.resolve(text, locale)
        messages = [{"role": "system", "content": system_prompt(loc.name, facts)},
                    *({"role": t.role, "content": t.content} for t in history),
                    {"role": "user", "content": text}]
        done, failures = await self.chain.chat(messages, max_tokens=max_tokens,
                                               timeout_s=timeout_s, locale=loc.code)
        return Reply(done.text, loc.code, done.backend, done.model, done.usage, done.latency_s,
                     done.adapter, det, failures)


def hosted_configured(settings: Settings) -> bool:
    """The hosted model may be called: allowed by residency and either keyed or self-hosted."""
    llm = settings.llm
    return settings.hosted_llm_allowed and (
        bool(llm.api_keys) or llm.base_url.rstrip("/") != OLLAMA_CLOUD)


def build_converser(settings: Settings | None = None, *,
                    slm: Callable[[str], EdgeSLM] | EdgeSLM | None = None,
                    client: httpx.AsyncClient | None = None,
                    ledger: UsageLedger | None = None,
                    responder: Callable[[str], str] | None = None,
                    local: bool = True) -> Converser:
    """Assemble the chain from settings: hosted (if allowed and keyed), local SLM, offline.

    `slm` overrides the local model (tests pass a fake); by default the installed models under
    `var/models` are used, and the SLM tier is left out when none is installed or when
    `local` is false.
    """
    settings = settings or get_settings()
    backends: list[ChatBackend] = []
    if hosted_configured(settings):
        backends.append(_HostedPrompt(hosted_backend(settings.llm, client=client)))
    if slm is None and local:
        from ahdt.models.language.slm import slm_factory

        slm = slm_factory(settings)
    if slm is not None and local:
        backends.append(SlmBackend(slm))
    backends.append(OfflineBackend(responder))
    return Converser(ChatChain(backends, ledger))
