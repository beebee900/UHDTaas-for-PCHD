"""One broker connection shared by all connectors of a process.

Every supplied `Connector.start` calls `transport.connect()`. For the Kafka and MQTT
transports (p1) that would open one producer or client per connector; `SharedTransport`
connects once, and its owner (the coupling service) closes it. In p0 it wraps
`InMemoryTransport`.
"""

from __future__ import annotations

import asyncio

from atra.connectors import Handler, Transport


class SharedTransport(Transport):
    def __init__(self, inner: Transport) -> None:
        self.inner = inner
        self._connected = False
        self._lock = asyncio.Lock()

    async def connect(self) -> None:
        async with self._lock:
            if not self._connected:
                await self.inner.connect()
                self._connected = True

    async def publish(self, topic: str, data: bytes) -> None:
        await self.inner.publish(topic, data)

    async def subscribe(self, topic: str, handler: Handler) -> None:
        await self.inner.subscribe(topic, handler)

    async def close(self) -> None:
        async with self._lock:
            if self._connected:
                await self.inner.close()
                self._connected = False
