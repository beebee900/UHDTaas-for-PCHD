"""Settings for every service: environment variables with the prefix `ATRA_` (design 02, 2.8).

Nested fields use `__`, for example `ATRA_AHDT__ACTIVE_LIMIT=20` or
`ATRA_BACKEND__GRAPH=neo4j`.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent

type Profile = Literal["p0", "p1", "p2", "p3", "p4", "full", "k8s"]


class BackendSwitches(BaseModel):
    """`memory` selects the in-process backend; any other value names the container backend."""

    timeseries: Literal["memory", "influxdb"] = "memory"
    fhir: Literal["memory", "hapi"] = "memory"
    graph: Literal["memory", "neo4j"] = "memory"
    vector: Literal["memory", "qdrant"] = "memory"
    object: Literal["memory", "minio"] = "memory"
    relational: Literal["memory", "postgres"] = "memory"
    cache: Literal["memory", "redis"] = "memory"
    bus: Literal["memory", "kafka", "mqtt"] = "memory"
    schema_registry: Literal["memory", "apicurio"] = "memory"
    policy: Literal["memory", "opa"] = "memory"
    identity: Literal["memory", "keycloak"] = "memory"
    secret: Literal["memory", "vault"] = "memory"
    workflow: Literal["memory", "temporal"] = "memory"
    model_registry: Literal["memory", "mlflow"] = "memory"
    trace: Literal["memory", "jaeger"] = "memory"
    imaging: Literal["memory", "orthanc"] = "memory"


class ServiceUrls(BaseModel):
    edge: str = "http://127.0.0.1:8095"
    ahdt: str = "http://127.0.0.1:8100"
    population: str = "http://127.0.0.1:8110"
    apdt: str = "http://127.0.0.1:8200"
    channels: str = "http://127.0.0.1:8300"


class InfraUrls(BaseModel):
    opa: str = "http://127.0.0.1:8181"
    influxdb: str = "http://127.0.0.1:8086"
    hapi: str = "http://127.0.0.1:8081/fhir"
    neo4j: str = "bolt://127.0.0.1:7687"
    qdrant: str = "http://127.0.0.1:6333"
    minio: str = "127.0.0.1:9000"
    postgres: str = "postgresql://atra:atra@127.0.0.1:5432/atra"
    redis: str = "redis://127.0.0.1:6379/0"
    kafka: str = "127.0.0.1:9092"
    mqtt: str = "127.0.0.1"
    apicurio: str = "http://127.0.0.1:8085/apis/registry/v3"
    keycloak: str = "http://127.0.0.1:8180/realms/atra"
    vault: str = "http://127.0.0.1:8250"
    temporal: str = "127.0.0.1:7233"
    mlflow: str = "http://127.0.0.1:5000"
    otlp: str = "http://127.0.0.1:4317"
    orthanc: str = "http://127.0.0.1:8042/dicom-web"


class AHDTSettings(BaseModel):
    active_limit: int = Field(10, ge=1)
    idle_release_s: float = Field(600, gt=0)
    grpc_port: int | None = Field(50051, ge=0, description="0 picks a free port; None disables")


class LLMSettings(BaseModel):
    """The hosted language model. `ollama` speaks the Ollama `/api/chat` API; `openai` speaks
    `/chat/completions`, which Groq, OpenRouter, Together and most other hosts also serve.

    `api_keys` takes one key or several, comma-separated in `ATRA_LLM__API_KEYS`. When a key is
    rate limited or refused, the next key answers and the refused key rests for `key_rest_s`.
    """

    provider: Literal["ollama", "openai", "offline"] = "ollama"
    base_url: str = "https://ollama.com"
    model: str = "gpt-oss:120b-cloud"
    api_keys: Annotated[list[SecretStr], NoDecode] = Field(default_factory=list)
    key_rest_s: float = Field(60.0, ge=0)
    timeout_s: float = 60.0
    edge_model_path: Path = ROOT / "var" / "models" / "qwen2.5-0.5b-instruct-q4_k_m.gguf"

    @field_validator("api_keys", mode="before")
    @classmethod
    def _split_keys(cls, value: Any) -> Any:
        if isinstance(value, str):
            return [k.strip() for k in value.split(",") if k.strip()]
        return value


class SecuritySettings(BaseModel):
    issuer: str = "https://atra.local/issuer"
    audience: str = "atra"
    token_ttl_s: int = 3600
    mtls: bool = False
    cors_origins: list[str] = ["http://127.0.0.1:8400", "http://localhost:8400"]
    pki_dir: Path = ROOT / "deploy" / "pki" / "out"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ATRA_", env_nested_delimiter="__",
                                      env_file=".env", extra="ignore")

    profile: Profile = "p0"
    residency: str = "NG"
    residency_mode: Literal["standard", "strict"] = "standard"
    var_dir: Path = ROOT / "var"
    contracts_dir: Path = ROOT / "contracts"
    kb_dir: Path = ROOT / "kb"
    backend: BackendSwitches = BackendSwitches()
    services: ServiceUrls = ServiceUrls()
    infra: InfraUrls = InfraUrls()
    ahdt: AHDTSettings = AHDTSettings()
    llm: LLMSettings = LLMSettings()
    security: SecuritySettings = SecuritySettings()
    ahdt_version: str = "1.0.0"

    @property
    def hosted_llm_allowed(self) -> bool:
        """Strict residency keeps every language task on the local small model."""
        return self.residency_mode == "standard" and self.llm.provider != "offline"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
