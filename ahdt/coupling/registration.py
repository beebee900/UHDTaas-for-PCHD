"""Registration of the connector contracts in the schema registry (design 04, 4.8).

p0 uses the in-process `FileSchemaRegistry` over `contracts/schemas/connectors/`; p1 uses
Apicurio behind the same `SchemaRegistryBackend` interface. A subject whose registered
schema differs from the code is contract drift and stops the registration.
"""

from __future__ import annotations

from typing import Any

from atra.backends.base import SchemaRegistryBackend
from atra.connection import WIRE_VERSION
from atra.connector_contracts import all_contracts, contract_json_schema
from atra.schemagen import WIRE_MODELS, model_schema, snake


class ContractDrift(RuntimeError):
    """A registered schema differs from the one the code defines."""


def expected_schemas() -> dict[tuple[str, str], dict[str, Any]]:
    """(subject, version) -> JSON Schema for every contract and the two wire shapes."""
    out: dict[tuple[str, str], dict[str, Any]] = {}
    for key, contract in all_contracts().items():
        name, version = key.split("/v")
        out[(name, version)] = contract_json_schema(contract)
    for wire in WIRE_MODELS:
        subject = snake(wire.__name__)
        out[(subject, WIRE_VERSION)] = model_schema(
            wire, f"connectors/{subject}.v{WIRE_VERSION}.schema.json")
    return out


async def register_contracts(registry: SchemaRegistryBackend) -> list[str]:
    """Register what is missing and check what is there. Returns `subject/vX.Y` added."""
    added: list[str] = []
    for (subject, version), schema in expected_schemas().items():
        try:
            existing = await registry.get(subject, version)
        except KeyError:
            await registry.register(subject, version, schema)
            added.append(f"{subject}/v{version}")
            continue
        if existing != schema:
            raise ContractDrift(f"{subject} v{version} in the registry differs from the code")
    return added
