"""OpenAPI documents of the five services, written to `contracts/openapi/` by `atra.schemagen`."""

from __future__ import annotations

import tempfile
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import yaml

from atra.backends import Backends
from atra.config import ROOT, Settings

SERVICES: Mapping[str, str] = {
    "ahdt": "ahdt.app", "apdt": "apdt.app", "population": "population.app",
    "channels": "channels.app", "edge": "edge.app",
}


def document(service: str) -> dict[str, Any]:
    import importlib

    module = importlib.import_module(SERVICES[service])
    build: Callable[..., Any] = module.build_app
    settings = Settings(var_dir=Path(tempfile.gettempdir()) / "atra-openapi")
    app = build(settings, backends=Backends(settings, service, ephemeral=True))
    spec: dict[str, Any] = app.openapi()
    return spec


def files() -> dict[Path, str]:
    out = {}
    for service in SERVICES:
        text = yaml.safe_dump(document(service), sort_keys=True, allow_unicode=True, width=100)
        out[ROOT / "contracts" / "openapi" / f"{service}.yaml"] = text
    return out

