"""`GET /v1/language/status`: which backends answer the conversation, in order, and their use.

Any signed-in user may read it. It names providers, models and the number of keys, never a key.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request

from ahdt.models.language.converse import hosted_configured
from ahdt.services.runtime import Runtime
from atra.service import authenticate, verifier_of


def mount_language_status(app: FastAPI, runtime: Runtime) -> None:
    @app.get("/v1/language/status", tags=["language"],
             summary="The conversation backends in the order they are tried, with their use")
    async def language_status(request: Request) -> dict[str, Any]:
        await authenticate(request.headers, await verifier_of(app))
        settings = runtime.settings
        chain = runtime.converser.chain
        hosted = None
        if hosted_configured(settings):
            hosted = {"provider": settings.llm.provider, "model": settings.llm.model,
                      "base_url": settings.llm.base_url, "keys": len(settings.llm.api_keys)}
        return {"residency_mode": settings.residency_mode, "hosted": hosted,
                "chain": [{"backend": b.name, "model": b.model} for b in chain.backends],
                "usage": chain.ledger.totals()}
