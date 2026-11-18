"""Logs, traces and metrics for every service (design 07, section 7.6).

- Logs: structlog JSON lines carrying `trace_id`, `span_id` and the bound context
  (`hdt_id`, `tenant_id`, `actor_role`, `agent`). Direct identifiers are redacted.
- Traces: OpenTelemetry. p0 keeps finished spans in memory (`span_store()`); other
  profiles export OTLP to Jaeger.
- Metrics: the Prometheus series named in 7.6.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import MutableMapping
from typing import Any

import structlog
from opentelemetry import trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

# Direct identifiers never reach logs above Layer 3 (NFR3).
REDACTED_KEYS = frozenset({"person_id", "national_id", "name", "given_name", "family_name",
                           "phone", "telephone", "email", "address", "birth_date"})

_span_store = InMemorySpanExporter()
_configured: set[str] = set()


def _redact(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    for key in REDACTED_KEYS.intersection(event):
        event[key] = "[redacted]"
    return event


def _add_trace(_: Any, __: str, event: MutableMapping[str, Any]) -> MutableMapping[str, Any]:
    ctx = trace.get_current_span().get_span_context()
    if ctx.is_valid:
        event.setdefault("trace_id", format(ctx.trace_id, "032x"))
        event.setdefault("span_id", format(ctx.span_id, "016x"))
    return event


def configure_logging(service: str, *, level: str = "INFO", json: bool = True) -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout,
                        level=getattr(logging, level.upper(), logging.INFO))
    renderer: Any = (structlog.processors.JSONRenderer() if json
                     else structlog.dev.ConsoleRenderer())
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _add_trace,
            _redact,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, level.upper(), logging.INFO)),
        cache_logger_on_first_use=False,
    )
    structlog.contextvars.bind_contextvars(service=service)


def get_logger(name: str | None = None) -> Any:
    return structlog.get_logger(name)


def bind(**context: Any) -> None:
    """Bind request context (hdt_id, tenant_id, actor_role, agent) to later log lines."""
    structlog.contextvars.bind_contextvars(**{k: v for k, v in context.items() if v is not None})


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


def configure_tracing(service: str, *, otlp_endpoint: str | None = None) -> TracerProvider:
    """One tracer provider per process; p0 keeps spans in memory."""
    current = trace.get_tracer_provider()
    if isinstance(current, TracerProvider):
        return current
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(SimpleSpanProcessor(_span_store))
    if otlp_endpoint:
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)))
    trace.set_tracer_provider(provider)
    return provider


def tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)


def span_store() -> InMemorySpanExporter:
    return _span_store


def current_trace_id() -> str | None:
    ctx = trace.get_current_span().get_span_context()
    return format(ctx.trace_id, "032x") if ctx.is_valid else None


class Metrics:
    """The Prometheus series of design 07, 7.6, in one registry per process."""

    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry or CollectorRegistry()
        r = self.registry
        self.tool_calls = Counter("atra_tool_calls_total", "AHDT tool calls",
                                  ["tool", "outcome"], registry=r)
        self.tool_latency = Histogram("atra_tool_latency_seconds", "AHDT tool latency",
                                      ["tool"], registry=r)
        self.gateway_cache_hits = Counter("atra_gateway_cache_hits_total",
                                          "Gateway cache hits", registry=r)
        self.connector_lag = Histogram("atra_connector_lag_seconds",
                                       "Send-to-deliver lag of connector messages",
                                       ["connector"], registry=r)
        self.connector_dlq = Counter("atra_connector_dlq_total", "Dead-lettered messages",
                                     ["connector"], registry=r)
        self.model_latency = Histogram("atra_model_latency_seconds", "Model run time",
                                       ["model_id"], registry=r)
        self.alerts_open = Gauge("atra_alerts_open", "Open alerts", registry=r)
        self.alert_ack = Histogram("atra_alert_ack_seconds", "Time to acknowledge an alert",
                                   registry=r)
        self.llm_tokens = Counter("atra_llm_tokens_total", "LLM tokens",
                                  ["provider", "kind"], registry=r)
        self.agent_errors = Counter("atra_agent_errors_total", "Agent errors", ["agent"],
                                    registry=r)


_metrics: Metrics | None = None


def metrics() -> Metrics:
    global _metrics
    if _metrics is None:
        _metrics = Metrics()
    return _metrics


def setup(service: str, *, level: str = "INFO", otlp_endpoint: str | None = None) -> None:
    """Configure logging and tracing once per process."""
    if service in _configured:
        return
    configure_logging(service, level=level)
    configure_tracing(service, otlp_endpoint=otlp_endpoint)
    _configured.add(service)
