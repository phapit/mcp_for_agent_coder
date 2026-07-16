"""Health live/ready và rate limit cho agent_service."""
import pytest
from fastapi.testclient import TestClient

import main


def _client(monkeypatch):
    monkeypatch.setattr(main, "SERVICE_API_KEY", "shared-secret")
    main._rate_buckets.clear()
    return TestClient(main.app)


def test_health_live_is_public(monkeypatch):
    client = _client(monkeypatch)

    for path in ("/health", "/health/live"):
        response = client.get(path)
        assert response.status_code == 200
        assert response.json()["service"] == "agent_service"


def test_health_ready_reports_dependencies(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(main, "repo", None)
    monkeypatch.setattr(main, "KNOWLEDGE_SERVICE_URL", "http://127.0.0.1:1")  # cổng chắc chắn đóng

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["git_repo"] == "not_available"
    assert body["checks"]["knowledge_service"].startswith("unreachable")


def test_rate_limit_returns_429(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(main, "RATE_LIMIT_PER_MINUTE", 2)

    headers = {"X-API-Key": "shared-secret"}
    assert client.get("/", headers=headers).status_code == 200
    assert client.get("/", headers=headers).status_code == 200
    response = client.get("/", headers=headers)

    assert response.status_code == 429
    main._rate_buckets.clear()


def test_startup_fails_without_api_key(monkeypatch):
    monkeypatch.setattr(main, "SERVICE_API_KEY", "")
    with pytest.raises(RuntimeError):
        with TestClient(main.app):
            pass
