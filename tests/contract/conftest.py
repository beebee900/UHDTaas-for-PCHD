import socket
import threading
import time

import pytest
import uvicorn

from atra.backends import Backends
from atra.config import AHDTSettings, InfraUrls, Settings


@pytest.fixture
def settings(tmp_path, opa):
    return Settings(var_dir=tmp_path, infra=InfraUrls(opa=opa.url),
                    ahdt=AHDTSettings(grpc_port=None))


@pytest.fixture
def backends(settings):
    return lambda service: Backends(settings, service, ephemeral=True)


class LiveServer:
    def __init__(self, app):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.server = uvicorn.Server(uvicorn.Config(app, port=self.port, log_level="warning",
                                                    lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    @property
    def url(self):
        return f"http://127.0.0.1:{self.port}"

    def __enter__(self):
        self.thread.start()
        deadline = time.monotonic() + 15
        while not self.server.started:
            if time.monotonic() > deadline:
                raise TimeoutError("server did not start")
            time.sleep(0.05)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(timeout=10)


@pytest.fixture
def live():
    return LiveServer
