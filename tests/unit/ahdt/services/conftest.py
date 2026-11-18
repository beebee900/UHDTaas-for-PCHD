import pytest

from ahdt.app import build_app
from atra.backends import Backends
from atra.config import Settings
from tests.contract.fixtures import output_id, seed


@pytest.fixture
async def app(tmp_path):
    settings = Settings(var_dir=tmp_path)
    backends = Backends(settings, "ahdt", ephemeral=True)
    application = build_app(settings, backends=backends, local_llm=False)
    await seed(application)
    yield application
    await backends.close()


@pytest.fixture
def services(app):
    return app.state.services


@pytest.fixture
def runtime(app):
    return app.state.runtime


@pytest.fixture
async def state_output(app):
    return await output_id(app)


@pytest.fixture
async def http(tmp_path, opa):
    """The seeded app behind HTTP, with the OPA server of profile p0."""
    from atra.config import AHDTSettings, InfraUrls

    settings = Settings(var_dir=tmp_path, infra=InfraUrls(opa=opa.url),
                        ahdt=AHDTSettings(grpc_port=None))
    backends = Backends(settings, "ahdt", ephemeral=True)
    application = build_app(settings, backends=backends, local_llm=False)
    await seed(application)
    yield application
    await backends.close()


def token(app, role, **kw):
    return app.state.backends.issuer.issue(f"user-{role}", role, tenant_id="fac-a", **kw)
