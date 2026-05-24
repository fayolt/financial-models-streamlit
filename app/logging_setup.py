"""Structured (JSON) logging configuration for both services.

DigitalOcean and Datadog ingest stdout. Plain `print()` makes filtering by
severity, service, or request impossible. This module configures the root
logger to emit JSON lines so downstream agents can index them properly.

When `ddtrace` is installed and active, trace/span IDs are injected into every
log record so Datadog Logs can correlate with APM traces automatically.

Call `configure_logging(service_name)` exactly once at the top of each
service entrypoint (Streamlit `app/streamlit_app.py`, FastAPI `api/main.py`).
"""
from __future__ import annotations

import logging
import sys

from pythonjsonlogger import jsonlogger


_configured = False

# Detect whether ddtrace is active so we can inject trace context into logs.
try:
    from ddtrace import tracer as _dd_tracer
    _DDTRACE = True
except ImportError:
    _dd_tracer = None  # type: ignore[assignment]
    _DDTRACE = False


class _ServiceFilter(logging.Filter):
    """Inject `service` and (when ddtrace is active) Datadog trace IDs."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def filter(self, record: logging.LogRecord) -> bool:
        record.service = self.service
        if _DDTRACE and _dd_tracer is not None:
            span = _dd_tracer.current_span()
            record.dd = {
                "trace_id": str(span.trace_id) if span else "0",
                "span_id": str(span.span_id) if span else "0",
            }
        return True


def configure_logging(service: str, level: int = logging.INFO) -> None:
    """Wire the root logger to emit JSON to stdout.

    Idempotent: safe to call multiple times (Streamlit re-imports the
    entrypoint module on every script rerun).
    """
    global _configured
    if _configured:
        return

    handler = logging.StreamHandler(stream=sys.stdout)
    handler.setFormatter(
        jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(service)s %(message)s",
            rename_fields={"asctime": "timestamp", "levelname": "level"},
        )
    )
    handler.addFilter(_ServiceFilter(service))

    root = logging.getLogger()
    # Replace any pre-existing handlers (uvicorn / streamlit set defaults).
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(handler)
    root.setLevel(level)

    # Quieten chatty libraries.
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    _configured = True
