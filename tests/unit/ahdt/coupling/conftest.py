import pytest

from ahdt.coupling.connectors import connector_class
from ahdt.coupling.inbox import CouplingInbox
from ahdt.coupling.manager import build_coupling, connector_name
from ahdt.coupling.policies import connector_policies, purpose_of, spec_of
from atra.backends.base import EventBusBackend
from atra.connectors import InMemoryTransport, TwinEndpoint
from atra.consent import ConsentRegistry
from atra.gateway import PatientConsent
from atra.policy import SyncPolicyClient

HDT = "hdt-c0ffee000001"
ALL_PURPOSES = {"care", "self_management", "public_health"}


class RecordingBus(EventBusBackend):
    def __init__(self):
        self.published = []

    async def publish(self, event):
        self.published.append(event)

    def subscribe(self, pattern, handler):
        raise NotImplementedError

    async def close(self):
        return None


class Rig:
    """One HDT's coupling over an in-memory bus, with real OPA policy decisions."""

    def __init__(self, opa_url, query_providers=None):
        self.transport = InMemoryTransport()
        self.consents = ConsentRegistry({HDT: PatientConsent(set(ALL_PURPOSES), set())})
        self.bus = RecordingBus()
        self.opa = SyncPolicyClient(opa_url)
        self.coupling = build_coupling(HDT, self.transport, consents=self.consents,
                                       opa=self.opa, events=self.bus, window_s=0,
                                       query_providers=query_providers)

    async def connector(self, name, source, target):
        key = connector_name(name, source, target)
        if key in self.coupling.connectors:
            return self.coupling.connectors[key], self.coupling.inbox
        c = self._standalone(name, source, target)
        await c.start()
        return c, self._inbox

    def _standalone(self, name, source, target):
        """Connectors outside the HDT (APDT to APDT), wired the same way."""
        self._inbox = CouplingInbox(HDT, window_s=0, events=self.bus)
        cls = connector_class(name, source)
        c = cls(TwinEndpoint(HDT, source, "fac-a"), TwinEndpoint(HDT, target, "fac-b"),
                self.transport, policies=connector_policies(HDT, self.consents, self.opa),
                purpose=purpose_of(spec_of(name)), name=connector_name(name, source, target),
                on_dead_letter=self._inbox.dead_lettered)
        c.on_deliver_to_target = self._inbox.deliver_fn(c, name, to_source=False)
        return c

    async def start(self):
        await self.coupling.start()

    async def stop(self):
        await self.coupling.stop()
        self.opa.close()


@pytest.fixture
async def rig(opa):
    r = Rig(opa.url)
    await r.start()
    yield r
    await r.stop()
