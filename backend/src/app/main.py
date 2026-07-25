from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from prometheus_fastapi_instrumentator import Instrumentator

from app.api.v1.router import api_router
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.telemetry import configure_tracing

configure_logging()
configure_tracing(service_name="prf-api")

app = FastAPI(title="PRF AI Pipeline", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in get_settings().cors_allowed_origins.split(",")],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(api_router, prefix="/api/v1")

FastAPIInstrumentor.instrument_app(app)
# Exposes GET /metrics (request count/latency by path+status). Pipeline-level
# counters (runs by terminal status, review pause rate) live in
# workers/metrics.py instead, since those are recorded from the Celery side
# where the actual terminal-status decision is made.
Instrumentator().instrument(app).expose(app)
