from datetime import timedelta

import pytest

from ahdt.agents.hub import AgentHub
from ahdt.app import build_app
from atra.backends import Backends
from atra.config import Settings
from atra.gateway import CallContext, Role
from tests.contract.fixtures import HDT, T0, _obs, seed
from tests.unit.ahdt.services.conftest import token  # noqa: F401

NOW = T0 + timedelta(hours=40)


@pytest.fixture
async def app(tmp_path):
    settings = Settings(var_dir=tmp_path)
    backends = Backends(settings, "ahdt", ephemeral=True)
    application = build_app(settings, backends=backends, local_llm=False)
    await seed(application)
    yield application
    await backends.close()


@pytest.fixture
def runtime(app):
    return app.state.runtime


@pytest.fixture
async def fresh(app, runtime):
    """Blood pressure, heart rate and glucose of A.O. observed one minute before NOW."""
    pipe = await runtime.pipeline()
    when = NOW - timedelta(minutes=1)
    raws = [_obs("now", "8480-6", 118.0, "mm[Hg]", when),
            _obs("now", "8462-4", 76.0, "mm[Hg]", when),
            _obs("now", "8867-4", 80.0, "/min", when),
            _obs("now", "15074-8", 5.4, "mmol/L", when)]
    result = await pipe.process(raws)
    assert result.counts()["rejected"] == 0, result.rejected


@pytest.fixture
def hub(app) -> AgentHub:
    return app.state.agents


@pytest.fixture
def ctx() -> CallContext:
    return CallContext(hdt_id=HDT, actor_role=Role.MEDICAL_OFFICER, actor_id="mo-1",
                       purpose="care")
