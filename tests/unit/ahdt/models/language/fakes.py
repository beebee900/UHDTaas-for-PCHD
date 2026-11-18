"""Test doubles: a fake Ollama server and a fake local model."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping, Sequence
from typing import Any

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from edge.slm import EdgeSLM


class FakeOllama:
    """`/api/chat` that echoes the language of the system prompt and counts tokens."""

    def __init__(self, *, delay_s: float = 0.0, status: int = 200,
                 refuse: Mapping[str, int] | None = None) -> None:
        self.requests: list[dict[str, Any]] = []
        self.headers: list[Mapping[str, str]] = []
        self.delay_s, self.status = delay_s, status
        self.refuse = dict(refuse or {})  # bearer key -> status code, for example 429
        self.app = FastAPI()
        self.app.post("/api/chat")(self.chat)
        self.app.post("/chat/completions")(self.completions)

    async def chat(self, request: Request) -> JSONResponse:
        body = await request.json()
        self.requests.append(body)
        self.headers.append(dict(request.headers))
        if self.delay_s:
            await asyncio.sleep(self.delay_s)
        if self.status != 200:
            return JSONResponse({"error": "down"}, status_code=self.status)
        key = request.headers.get("authorization", "").removeprefix("Bearer ")
        if key in self.refuse:
            return JSONResponse({"error": "limit"}, status_code=self.refuse[key])
        system = body["messages"][0]["content"]
        lang = system.split("Reply in ")[1].split(" in one")[0]
        return JSONResponse({
            "model": body["model"], "message": {"role": "assistant", "content": f"[{lang}] ok"},
            "prompt_eval_count": 21, "eval_count": 4, "done": True})

    async def completions(self, request: Request) -> JSONResponse:
        body = await request.json()
        self.requests.append(body)
        self.headers.append(dict(request.headers))
        return JSONResponse({"model": body["model"],
                             "choices": [{"message": {"role": "assistant", "content": "ok"}}],
                             "usage": {"prompt_tokens": 12, "completion_tokens": 1}})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app))


class FakeSLM:
    """An `EdgeSLM` whose reply names the adapter it was built for."""

    def __init__(self, adapter: str | None) -> None:
        self.adapter = adapter
        self.calls: list[Sequence[Mapping[str, str]]] = []

    def chat(self, messages: Sequence[Mapping[str, str]], *, max_tokens: int) -> str:
        self.calls.append(messages)
        return f"local:{self.adapter}"

    def count_tokens(self, text: str) -> int:
        return len(text.split())


class FakeSLMFactory:
    def __init__(self) -> None:
        self.built: dict[str, FakeSLM] = {}

    def __call__(self, locale: str) -> EdgeSLM:
        adapter = None if locale == "en" else f"lora-{locale}"
        return self.built.setdefault(locale, FakeSLM(adapter))
