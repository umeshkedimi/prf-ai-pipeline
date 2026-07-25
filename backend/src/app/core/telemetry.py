"""OpenTelemetry tracing setup, shared by the API and the Celery worker.

The two processes are instrumented differently (FastAPIInstrumentor vs
CeleryInstrumentor) but share one tracer provider setup here so a trace
started by an API request and continued by a Celery task renders as a single
trace in the backend, not two disconnected ones. CeleryInstrumentor is what
makes that continuity work: it injects the current trace context into task
message headers on publish and restores it on the worker side, so the
producer/consumer boundary between `POST /workflow/run` and `run_workflow`
doesn't break the trace.
"""

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.core.config import get_settings

_configured = False


def configure_tracing(service_name: str) -> None:
    global _configured
    if _configured:
        return

    settings = get_settings()
    provider = TracerProvider(resource=Resource.create({SERVICE_NAME: service_name}))
    exporter = OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint, insecure=True)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    _configured = True


def get_tracer(name: str) -> trace.Tracer:
    return trace.get_tracer(name)
