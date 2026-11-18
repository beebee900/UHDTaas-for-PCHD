"""Edge settings: environment variables with the prefix `ATRA_EDGE__` (design 02, 2.8).

One edge instance serves one facility or home (`ATRA_EDGE__SITE=edge-home-001`).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from atra.config import ROOT

type LinkProfile = Literal["wifi", "4g", "2g", "offline"]


class EdgeSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATRA_EDGE__", extra="ignore")

    site: str = "edge-fac-a"
    data_dir: Path = ROOT / "var" / "edge"
    link: LinkProfile = "wifi"
    ahdt_grpc: str = "127.0.0.1:50051"
    mqtt_host: str = "127.0.0.1"
    mqtt_port: int = Field(8883, ge=1, le=65535)
    mqtt_tls: bool = True
    coap_port: int = Field(5683, ge=0, le=65535)
    batch_size: int = Field(500, ge=1)
    retry_s: float = Field(5.0, gt=0)
    ingest_timeout_s: float = Field(120.0, gt=0)
    feature_window_s: float = Field(60.0, gt=0)
    models_dir: Path = ROOT / "var" / "models" / "edge"
    slm: Literal["llama_cpp", "offline"] = "offline"

    def path(self, name: str) -> Path:
        directory = self.data_dir / self.site
        directory.mkdir(parents=True, exist_ok=True)
        return directory / name
