import pytest

from atra.policy import OPAProcess


@pytest.fixture(scope="session")
def opa():
    """OPA server over policies/opa as a local process, as in profile p0."""
    with OPAProcess() as proc:
        yield proc
