"""JSON log formatter, correlation ID contextvar và middleware X-Request-ID."""
import json
import logging

from fastapi.testclient import TestClient

import main
import observability


def _client(monkeypatch):
    monkeypatch.setattr(main, "SERVICE_API_KEY", "shared-secret")
    main._rate_buckets.clear()
    return TestClient(main.app)


def _format(record_kwargs=None, extra=None):
    formatter = observability.JsonFormatter("test_service")
    record = logging.LogRecord(
        name="test.logger", level=logging.INFO, pathname=__file__, lineno=1,
        msg="my_event", args=(), exc_info=None, **(record_kwargs or {}),
    )
    for key, value in (extra or {}).items():
        setattr(record, key, value)
    return json.loads(formatter.format(record))


def test_json_formatter_emits_structured_fields():
    payload = _format(extra={"duration_ms": 12.5, "model": "llama3.2:3b"})

    assert payload["event"] == "my_event"
    assert payload["level"] == "INFO"
    assert payload["service"] == "test_service"
    assert payload["logger"] == "test.logger"
    assert payload["duration_ms"] == 12.5
    assert payload["model"] == "llama3.2:3b"
    assert "timestamp" in payload


def test_json_formatter_includes_correlation_id():
    token = observability._correlation_id.set(None)
    try:
        assert "correlation_id" not in _format()
        observability.set_correlation_id("abc-123")
        assert _format()["correlation_id"] == "abc-123"
    finally:
        observability._correlation_id.reset(token)


def test_set_correlation_id_generates_when_missing():
    token = observability._correlation_id.set(None)
    try:
        generated = observability.set_correlation_id(None)
        assert generated
        assert observability.get_correlation_id() == generated
        assert observability.set_correlation_id("  ") != ""
    finally:
        observability._correlation_id.reset(token)


def test_response_carries_generated_request_id(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/", headers={"X-API-Key": "shared-secret"})

    assert response.status_code == 200
    assert response.headers.get("X-Request-ID")


def test_response_echoes_provided_request_id(monkeypatch):
    client = _client(monkeypatch)

    response = client.get(
        "/", headers={"X-API-Key": "shared-secret", "X-Request-ID": "trace-me-42"}
    )

    assert response.headers.get("X-Request-ID") == "trace-me-42"


def test_log_llm_usage_reads_openai_style_usage(caplog):
    class Usage:
        prompt_tokens = 10
        completion_tokens = 5
        total_tokens = 15

    class Completion:
        usage = Usage()

    logger = logging.getLogger("test.llm")
    with caplog.at_level(logging.INFO, logger="test.llm"):
        import time

        observability.log_llm_usage(
            logger, "llm_completion", model="m", started=time.perf_counter(),
            completion=Completion(), purpose="answer",
        )

    record = caplog.records[-1]
    assert record.prompt_tokens == 10
    assert record.completion_tokens == 5
    assert record.total_tokens == 15
    assert record.purpose == "answer"
    assert record.duration_ms >= 0
