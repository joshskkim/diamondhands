"""OpenTelemetry tracing setup.

Configures an OTLP-HTTP exporter to the same collector the Java API uses and instruments
httpx so outbound calls carry the W3C ``traceparent`` header. The Spring API already continues
incoming traceparent (micrometer-tracing-bridge-otel), so one Claude request shows up in Jaeger
as a single trace: diamond-mcp (server span) -> httpx (client span) -> diamond-api -> JDBC.
"""

from __future__ import annotations

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from . import config

_initialized = False


def init_tracing() -> bool:
    """Idempotently set up the tracer provider + httpx instrumentation. Returns True if on."""
    global _initialized
    if _initialized or not config.TRACING_ENABLED:
        return False

    provider = TracerProvider(
        resource=Resource.create({"service.name": config.OTEL_SERVICE_NAME})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=config.OTLP_TRACING_ENDPOINT))
    )
    trace.set_tracer_provider(provider)
    # Inject traceparent on outbound calls + create a client span per request.
    HTTPXClientInstrumentor().instrument()
    _initialized = True
    return True
