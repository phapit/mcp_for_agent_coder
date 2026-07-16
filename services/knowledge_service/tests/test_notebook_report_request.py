import pytest
from pydantic import ValidationError

import main

BASE = {"project_name": "projectA", "notebook_env": "env_a"}


def test_prompt_at_limit_is_accepted():
    prompt = "a" * 1024
    request = main.NotebookReportRequest(**BASE, prompt=prompt)
    assert request.prompt == prompt


def test_prompt_over_limit_is_rejected():
    prompt = "a" * 1025

    with pytest.raises(ValidationError, match="1024"):
        main.NotebookReportRequest(**BASE, prompt=prompt)


def test_prompt_over_limit_via_api_returns_422(monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(main, "SERVICE_API_KEY", "shared-secret")
    client = TestClient(main.app)

    response = client.post(
        "/notebook-reports",
        json={**BASE, "prompt": "a" * 1025},
        headers={"X-API-Key": "shared-secret"},
    )

    assert response.status_code == 422
