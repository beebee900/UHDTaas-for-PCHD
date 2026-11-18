"""Generate `contracts/` and the OPA data file from the Python contract types.

    python -m atra.schemagen           write every generated file
    python -m atra.schemagen --check   exit 1 when a file differs from what would be generated

The contract test runs the check, so the files and the code cannot drift apart.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from atra import contracts as c
from atra.config import ROOT
from atra.connection import WIRE_VERSION, ConnectorEnvelope, DeadLetterRecord
from atra.connector_contracts import (
    RANGE_GUARD,
    all_contracts,
    connector_purposes,
    contract_json_schema,
)
from atra.gateway import AHDT_TOOLS, ToolSpec
from atra.policy import policy_data_json

CONTRACTS = ROOT / "contracts"
SCHEMA_BASE = "https://atra.local/schemas"

CORE_MODELS: tuple[type[BaseModel], ...] = (
    c.TwinDefinition, c.Scenario, c.ObservationRecord, c.ModelRegistryEntry, c.ModelOutput,
    c.Trajectory, c.InstanceRecord, c.FacetView, c.ToolMeta, c.EventEnvelope,
    c.AHDTExplanation, c.Goal, c.AgentResult, c.AuditRecord,
)
APDT_MODELS: tuple[type[BaseModel], ...] = (
    c.Episode, c.Interrupt, c.Recommendation, c.ClinicalDecision, c.ExplanationBundle,
    *c.APDT_API_MODELS,
)

WIRE_MODELS: tuple[type[BaseModel], ...] = (ConnectorEnvelope, DeadLetterRecord)

MCP_SERVERS: Mapping[str, str] = {
    "ahdt-data": "6.1", "ahdt-model": "6.2", "ahdt-xai": "6.3", "ahdt-cognitive": "6.4",
}


def snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])", "_", name).lower()


def model_schema(model: type[BaseModel], schema_id: str) -> dict[str, Any]:
    schema = model.model_json_schema(by_alias=True, mode="validation")
    return {"$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": f"{SCHEMA_BASE}/{schema_id}", **schema}


def output_schema(model: type[BaseModel]) -> dict[str, Any]:
    """A tool's response schema plus the `_meta` block every response carries (3.6)."""
    schema = model.model_json_schema(by_alias=True)
    meta = c.ToolMeta.model_json_schema(by_alias=True)
    defs = {**schema.pop("$defs", {}), **meta.pop("$defs", {}), "ToolMeta": meta}
    schema["properties"] = {**schema.get("properties", {}),
                            "_meta": {"$ref": "#/$defs/ToolMeta"}}
    return {**schema, "$defs": defs}


def tool_descriptor(spec: ToolSpec) -> dict[str, Any]:
    """`ToolSpec.descriptor()` with the argument and response schemas of design 03, 3.6."""
    base = spec.descriptor()
    args = c.TOOL_ARGS[spec.name].model_json_schema(by_alias=True)
    response = output_schema(c.TOOL_RESPONSES[spec.name])
    return {**base, "inputSchema": args, "outputSchema": response,
            "annotations": {"readOnlyHint": spec.name.startswith("ahdt.data."),
                            "x-atra-sublayer": spec.sublayer,
                            "x-atra-reaches-layer": spec.reaches_layer,
                            "x-atra-forces-fork": spec.forces_fork}}


def service_tool_descriptor(name: str, description: str, args: type[BaseModel],
                            response: type[BaseModel]) -> dict[str, Any]:
    return {"name": name, "description": description,
            "inputSchema": args.model_json_schema(by_alias=True),
            "outputSchema": output_schema(response)}


POPULATION_DESCRIPTIONS = {
    "population.priors": "Condition prevalence priors by age band, sex, region and season",
    "population.norms": "Population percentiles of a field by age band and sex",
    "population.contribute": "De-identified contribution, stored only when k-anonymity holds",
}
APDT_DESCRIPTIONS = {
    "apdt.episode.summary": "Summary of one care episode",
    "apdt.diagnosis.differential": "Current differential diagnosis with probabilities",
    "apdt.treatment.options": "Ranked treatment options for a diagnosis",
    "apdt.explain": "Explanation bundle of a recommendation for an audience",
    "apdt.consent.get": "The patient's current consent for AHDT access",
}


def _dump(obj: Any) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def generated_files(*, openapi: bool = True) -> dict[Path, str]:
    files: dict[Path, str] = {}
    schemas = CONTRACTS / "schemas"
    for model in CORE_MODELS:
        sid = f"{snake(model.__name__)}.schema.json"
        files[schemas / sid] = _dump(model_schema(model, sid))
    for model in APDT_MODELS:
        sid = f"apdt/{snake(model.__name__)}.schema.json"
        files[schemas / sid] = _dump(model_schema(model, sid))
    for name, args in c.TOOL_ARGS.items():
        files[schemas / "tools" / f"{name}.args.schema.json"] = _dump(
            model_schema(args, f"tools/{name}.args.schema.json"))
        files[schemas / "tools" / f"{name}.response.schema.json"] = _dump(
            model_schema(c.TOOL_RESPONSES[name], f"tools/{name}.response.schema.json"))
    for key, contract in all_contracts().items():
        name, version = key.split("/v")
        files[schemas / "connectors" / f"{name}.v{version}.schema.json"] = _dump(
            contract_json_schema(contract))
    for wire in WIRE_MODELS:
        sid = f"connectors/{snake(wire.__name__)}.v{WIRE_VERSION}.schema.json"
        files[schemas / sid] = _dump(model_schema(wire, sid))

    for server, sublayer in MCP_SERVERS.items():
        tools = [tool_descriptor(t) for t in AHDT_TOOLS if t.sublayer == sublayer]
        files[CONTRACTS / "mcp" / f"{server}.json"] = _dump({"server": server, "tools": tools})
    files[CONTRACTS / "mcp" / "population.json"] = _dump({"server": "population", "tools": [
        service_tool_descriptor(n, POPULATION_DESCRIPTIONS[n], a, c.POPULATION_TOOL_RESPONSES[n])
        for n, a in c.POPULATION_TOOL_ARGS.items()]})
    files[CONTRACTS / "mcp" / "apdt.json"] = _dump({"server": "apdt", "tools": [
        service_tool_descriptor(n, APDT_DESCRIPTIONS[n], a, c.APDT_TOOL_RESPONSES[n])
        for n, a in c.APDT_TOOL_ARGS.items()]})

    files[ROOT / "policies" / "opa" / "data.json"] = policy_data_json({
        "role_tools": {r.value: sorted(t) for r, t in sorted(c.ATRA_ROLE_TOOLS.items(),
                                                            key=lambda kv: kv[0].value)},
        "connector_purposes": connector_purposes(),
        "range_guard": {k: list(v) for k, v in sorted(RANGE_GUARD.items())},
        "consent_categories": {k: sorted(v) for k, v in sorted(c.CONSENT_CATEGORIES.items())},
        "purpose_hl7": {p.value: code for p, code in c.PURPOSE_HL7.items()},
    })
    if openapi:
        from atra import openapi as openapi_docs

        files.update(openapi_docs.files())
    return files


def drift(files: Mapping[Path, str]) -> list[Path]:
    return [p for p, text in files.items()
            if not p.exists() or p.read_text(encoding="utf-8") != text]


def write(files: Mapping[Path, str]) -> list[Path]:
    changed = drift(files)
    for path in changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(files[path], encoding="utf-8")
    return changed


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    ns = parser.parse_args(list(argv) if argv is not None else None)
    files = generated_files()
    if ns.check:
        stale = drift(files)
        for p in stale:
            print(f"out of date: {p.relative_to(ROOT)}")
        return 1 if stale else 0
    for p in write(files):
        print(f"wrote {p.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
