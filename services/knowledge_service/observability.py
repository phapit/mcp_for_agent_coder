"""Structured JSON logging + correlation ID (Phase 1 observability).

Stdlib-only: JSON formatter over `logging`, correlation ID in a contextvar so
every log line in the same request/job carries the same ID, and helpers to log
LLM usage (tokens) and operation durations as machine-parseable fields.
"""

from __future__ import annotations

import contextvars
import json
import logging
import os
import time
import uuid
from datetime import datetime, timezone

REQUEST_ID_HEADER = "X-Request-ID"

_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "correlation_id", default=None
)

# Attributes present on every LogRecord; anything else was passed via `extra`.
_STANDARD_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
) | {"message", "asctime", "taskName"}


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def set_correlation_id(value: str | None = None) -> str:
    """Set (or generate) the correlation ID for the current context and return it."""
    value = (value or "").strip() or uuid.uuid4().hex
    _correlation_id.set(value)
    return value


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str):
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": self.service_name,
            "logger": record.name,
            "event": record.getMessage(),
        }
        correlation_id = _correlation_id.get()
        if correlation_id:
            payload["correlation_id"] = correlation_id
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(service_name: str) -> None:
    """Route all loggers (including uvicorn's) through one JSON handler on root."""
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter(service_name))
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers = []
        uvicorn_logger.propagate = True


def duration_ms(started: float) -> float:
    """Elapsed milliseconds since a time.perf_counter() checkpoint."""
    return round((time.perf_counter() - started) * 1000, 1)


def log_llm_usage(logger: logging.Logger, event: str, *, model: str, started: float, completion, **fields) -> None:
    """Log one LLM call with duration and token usage (OpenAI- or Anthropic-style)."""
    usage = getattr(completion, "usage", None)
    extra = {
        "model": model,
        "duration_ms": duration_ms(started),
        # OpenAI-compatible responses (OpenAI, Ollama) expose prompt/completion tokens.
        "prompt_tokens": getattr(usage, "prompt_tokens", None) or getattr(usage, "input_tokens", None),
        "completion_tokens": getattr(usage, "completion_tokens", None) or getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
        **fields,
    }
    logger.info(event, extra=extra)
