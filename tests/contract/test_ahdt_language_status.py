"""`GET /v1/language/status` names the conversation backends and never a key."""

import httpx
from pydantic import SecretStr

from ahdt.app import build_app
from atra.config import LLMSettings
from atra.contracts import Role


async def status(settings, backends):
    app = build_app(settings, backends=backends("ahdt"), local_llm=False)
    token = app.state.backends.issuer.issue("person.ao", Role.PERSON)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                 base_url="http://ahdt") as cl:
        r = await cl.get("/v1/language/status", headers={"Authorization": f"Bearer {token}"})
        anonymous = await cl.get("/v1/language/status")
    return r, anonymous


async def test_without_keys_the_offline_model_answers(settings, backends):
    r, anonymous = await status(settings, backends)
    assert r.status_code == 200 and anonymous.status_code == 401
    body = r.json()
    assert body["hosted"] is None
    assert [b["backend"] for b in body["chain"]] == ["offline"]


async def test_keys_are_counted_not_shown(settings, backends):
    keyed = settings.model_copy(update={"llm": LLMSettings(
        api_keys=[SecretStr("first-secret"), SecretStr("second-secret")])})
    r, _ = await status(keyed, backends)
    body = r.json()
    assert body["hosted"]["keys"] == 2 and body["chain"][0]["backend"] == "ollama"
    assert "secret" not in r.text
