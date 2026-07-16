"""Correlation ID middleware và JSON logging cho agent_service."""
import json
import logging

from fastapi.testclient import TestClient

import main
import observability


def _client(monkeypatch):
    monkeypatch.setattr(main, "SERVICE_API_KEY", "shared-secret")
    main._rate_buckets.clear()
    return TestClient(main.app)


def test_response_carries_request_id(monkeypatch):
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


def test_json_formatter_output_is_valid_json():
    formatter = observability.JsonFormatter("agent_service")
    record = logging.LogRecord(
        name="test", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hello", args=(), exc_info=None,
    )

    payload = json.loads(formatter.format(record))

    assert payload["event"] == "hello"
    assert payload["service"] == "agent_service"
