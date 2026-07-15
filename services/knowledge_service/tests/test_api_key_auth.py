from fastapi.testclient import TestClient

import main


def test_health_is_public(monkeypatch):
    monkeypatch.setattr(main, "SERVICE_API_KEY", "shared-secret")
    client = TestClient(main.app)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json()["service"] == "knowledge_service"


def test_root_requires_api_key(monkeypatch):
    monkeypatch.setattr(main, "SERVICE_API_KEY", "shared-secret")
    client = TestClient(main.app)

    response = client.get("/")

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid or missing API key."


def test_root_accepts_valid_api_key(monkeypatch):
    monkeypatch.setattr(main, "SERVICE_API_KEY", "shared-secret")
    client = TestClient(main.app)

    response = client.get("/", headers={"X-API-Key": "shared-secret"})

    assert response.status_code == 200
    assert response.json()["message"] == "Knowledge Curator Service is running."
