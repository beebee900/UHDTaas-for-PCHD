"""Published parameter sets of the Layer 4 models (design 01, rule R3; design 03, 3.4).

Each model has one YAML file next to its module. Every parameter names its source, so a
model card can list where each number comes from. A value that could not be checked
against its primary source is marked `verified: false`; an assumed value is marked
`assumption: true` with a justification.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from functools import cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, model_validator

MODELS_DIR = Path(__file__).resolve().parent


class Source(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    citation: str
    via: str | None = None
    url: str | None = None


class Param(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float
    unit: str
    source: str
    note: str | None = None
    verified: bool = True
    assumption: bool = False
    justification: str | None = None
    calibrate: bool = False
    prior_cv: float | None = None
    bounds: tuple[float, float] | None = None

    @model_validator(mode="after")
    def _justified(self) -> Param:
        if (self.assumption or not self.verified) and not self.justification:
            raise ValueError("an assumed or unverified parameter needs a justification")
        return self


class ParamSet(BaseModel):
    """The parameters of one model, with the sources they come from."""

    model_config = ConfigDict(extra="forbid")

    model_id: str
    sources: list[Source]
    params: dict[str, Param]

    @model_validator(mode="after")
    def _sources_known(self) -> ParamSet:
        known = {s.id for s in self.sources}
        for name, p in self.params.items():
            if p.source not in known:
                raise ValueError(f"{self.model_id}: {name} cites unknown source {p.source}")
        return self

    @property
    def values(self) -> dict[str, float]:
        return {k: p.value for k, p in self.params.items()}

    def calibratable(self) -> list[str]:
        return [k for k, p in self.params.items() if p.calibrate]

    def unverified(self) -> Iterator[str]:
        return (k for k, p in self.params.items() if not p.verified or p.assumption)

    def citation(self) -> str:
        return "; ".join(s.citation for s in self.sources)


def params_path(module_file: str, stem: str) -> Path:
    return Path(module_file).resolve().parent / f"{stem}.params.yaml"


@cache
def load_params(path: Path) -> ParamSet:
    with path.open(encoding="utf-8") as fh:
        data: Mapping[str, Any] = yaml.safe_load(fh)
    return ParamSet.model_validate(data)


def all_param_files() -> list[Path]:
    return sorted(MODELS_DIR.rglob("*.params.yaml"))
