"""Health live/ready, rate limit, giới hạn upload cho knowledge_service."""
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
        assert response.json()["service"] == "knowledge_service"


def test_health_ready_reports_missing_dependencies(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(main, "qdrant_client", None)
    monkeypatch.setattr(main, "mongo_client", None)
    monkeypatch.setattr(main, "embeddings", None)
    monkeypatch.setattr(main, "ollama_client", None)
    monkeypatch.setattr(main, "openai_client", None)

    response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    assert body["checks"]["qdrant"] == "not_initialized"
    assert body["checks"]["mongodb"] == "not_initialized"
    assert body["checks"]["embedding_model"] == "not_initialized"


def test_rate_limit_returns_429(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(main, "RATE_LIMIT_PER_MINUTE", 2)

    headers = {"X-API-Key": "shared-secret"}
    assert client.get("/", headers=headers).status_code == 200
    assert client.get("/", headers=headers).status_code == 200
    response = client.get("/", headers=headers)

    assert response.status_code == 429
    assert "Retry-After" in response.headers
    main._rate_buckets.clear()


def test_rate_limit_does_not_apply_to_health(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(main, "RATE_LIMIT_PER_MINUTE", 1)

    for _ in range(5):
        assert client.get("/health/live").status_code == 200
    main._rate_buckets.clear()


def test_upload_over_limit_is_rejected(monkeypatch):
    client = _client(monkeypatch)
    monkeypatch.setattr(main, "MAX_UPLOAD_BYTES", 10)

    response = client.post(
        "/ingest-excel/upload",
        headers={"X-API-Key": "shared-secret"},
        files={"file": ("big.xlsx", b"x" * 100)},
    )

    assert response.status_code == 413


def test_startup_fails_without_api_key(monkeypatch):
    import pytest

    monkeypatch.setattr(main, "SERVICE_API_KEY", "")
    with pytest.raises(RuntimeError):
        with TestClient(main.app):
            pass
