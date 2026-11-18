"""Bluetooth GATT health characteristics: one module per characteristic, each with
`encode(measurement) -> bytes` and `decode(bytes) -> measurement`."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from edge.devices.decode.gatt import blood_pressure, glucose, heart_rate, plx, temperature, weight
from edge.devices.decode.gatt._wire import DateTime, DecodeError

CHARACTERISTICS = {
    m.UUID: m for m in (heart_rate, blood_pressure, glucose, plx, weight, temperature)
}


def decode(uuid: int, data: bytes) -> Any:
    """Decode the value of the characteristic with this 16-bit UUID."""
    try:
        module = CHARACTERISTICS[uuid]
    except KeyError:
        raise DecodeError(f"no decoder for characteristic 0x{uuid:04X}") from None
    decoder: Callable[[bytes], Any] = module.decode
    return decoder(data)


__all__ = ["CHARACTERISTICS", "DateTime", "DecodeError", "blood_pressure", "decode", "glucose",
           "heart_rate", "plx", "temperature", "weight"]
