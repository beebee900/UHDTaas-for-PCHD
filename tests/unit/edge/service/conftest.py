import pytest

from atra.backends import Backends
from atra.clock import SimClock
from atra.config import AHDTSettings, InfraUrls, Settings
from edge.config import EdgeSettings
from tests.unit.edge.service.support import START


@pytest.fixture
def settings(tmp_path, opa):
    return Settings(var_dir=tmp_path, infra=InfraUrls(opa=opa.url),
                    ahdt=AHDTSettings(grpc_port=None))


@pytest.fixture
def backends(settings):
    return lambda service: Backends(settings, service, ephemeral=True)


@pytest.fixture
def clock():
    return SimClock(manual=True, start=START)


@pytest.fixture
def edge_settings(tmp_path):
    return EdgeSettings(site="edge-home-001", data_dir=tmp_path / "edge",
                        models_dir=tmp_path / "models")
