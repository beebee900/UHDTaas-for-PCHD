"""Model outputs of the AHDT services, kept for explanation (design 04, 4.7.4).

Each output is appended to `lake.outputs` with the inputs the model ran on and the instance
state it started from, and its run is recorded in W3C PROV next to the observations it used.
`lookup` answers the XAI service from memory or, after a restart, from the lake.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from ahdt.stores.lake import Lake
from ahdt.xai.causal import ProvenanceRecorder
from ahdt.xai.service import OutputRecord
from atra.provenance import ProvenanceStore


def _plain(value: Any) -> Any:
    if hasattr(value, "tolist"):
        return value.tolist()
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [_plain(v) for v in value]
    return value


@dataclass(frozen=True)
class StoredOutput:
    output_id: str
    model_id: str
    version: str
    hdt_id: str
    kind: str
    twin: str
    values: Mapping[str, Any]
    inputs: Mapping[str, Any] = field(default_factory=dict)
    state: Mapping[str, Any] = field(default_factory=dict)
    params: Mapping[str, Any] = field(default_factory=dict)
    window: Sequence[Mapping[str, Any]] = ()
    sources: Mapping[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def body(self) -> str:
        return json.dumps(_plain({
            "kind": self.kind, "twin": self.twin, "values": self.values, "inputs": self.inputs,
            "state": self.state, "params": self.params, "window": list(self.window),
            "sources": self.sources, "created_at": self.created_at}), default=str)

    def record(self) -> OutputRecord:
        return OutputRecord(self.output_id, self.model_id, self.version, self.hdt_id,
                            dict(self.inputs))


class OutputStore:
    def __init__(self, lake: Lake, provenance: ProvenanceStore) -> None:
        self.lake = lake
        self.recorder = ProvenanceRecorder(provenance)
        self._memory: dict[str, StoredOutput] = {}

    def put(self, out: StoredOutput, *, used: Sequence[str] = ()) -> StoredOutput:
        self._memory[out.output_id] = out
        self.lake.append("outputs", [{
            "output_id": out.output_id, "hdt_id": out.hdt_id, "model_id": out.model_id,
            "version": out.version, "body": out.body(), "ingested_at": out.created_at}])
        self.recorder.model_run(out.output_id, out.model_id, out.version, hdt_id=out.hdt_id,
                                used=list(used), twin=out.twin)
        return out

    def get(self, output_id: str) -> StoredOutput | None:
        found = self._memory.get(output_id)
        if found is not None:
            return found
        rows = self.lake.query(
            "SELECT output_id, hdt_id, model_id, version, body FROM outputs"
            " WHERE output_id = ? LIMIT 1", [output_id], table="outputs")
        if not rows:
            return None
        row = rows[0]
        body = json.loads(row["body"])
        out = StoredOutput(
            output_id=row["output_id"], model_id=row["model_id"], version=row["version"],
            hdt_id=row["hdt_id"], kind=body["kind"], twin=body["twin"], values=body["values"],
            inputs=body["inputs"], state=body["state"], params=body.get("params", {}),
            window=body.get("window", ()), sources=body.get("sources", {}),
            created_at=datetime.fromisoformat(body["created_at"]))
        self._memory[output_id] = out
        return out

    async def lookup(self, output_id: str) -> OutputRecord | None:
        found = self.get(output_id)
        return found.record() if found else None
