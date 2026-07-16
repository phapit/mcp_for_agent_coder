from fastapi.testclient import TestClient

import client_requests
import main

HEADERS = {"X-API-Key": "shared-secret"}


class FakeClientRequestStore:
    """In-memory thay cho Mongo trong test."""

    def __init__(self):
        self.records = {}
        self._counter = 0

    def create(self, title, description, request_type, project=None, requester=None):
        self._counter += 1
        record = {
            "request_id": f"req-test{self._counter}",
            "title": title,
            "description": description,
            "request_type": request_type,
            "project": project,
            "requester": requester,
            "status": "new",
            "created_at": "2026-01-01T00:00:00+00:00",
            "updated_at": "2026-01-01T00:00:00+00:00",
            "context": None,
        }
        self.records[record["request_id"]] = record
        return {**record}

    def list(self, limit=50):
        return [
            {k: v for k, v in r.items() if k != "description"}
            for r in list(self.records.values())[:limit]
        ]

    def get(self, request_id):
        record = self.records.get(request_id)
        return {**record} if record else None

    def save_context(self, request_id, package):
        if request_id not in self.records:
            return False
        self.records[request_id]["context"] = package
        return True


SPEC_MATCH = {
    "text": "Session của người dùng tồn tại tối đa 28 ngày.",
    "source": "docs/imported/session-spec.md",
    "heading": "Vòng đời session",
    "start_line": 10,
    "end_line": 14,
    "vector_score": 0.9,
    "keyword_score": None,
    "rerank_score": None,
}


def _client(monkeypatch, matches):
    monkeypatch.setattr(main, "SERVICE_API_KEY", "shared-secret")
    monkeypatch.setattr(main, "client_request_store", FakeClientRequestStore())
    monkeypatch.setattr(main, "_retrieve", lambda query, limit, filters: (matches, {"mode": "hybrid"}))
    return TestClient(main.app)


def _create(client, **overrides):
    payload = {
        "title": "Cho phép gia hạn session",
        "description": "Khách muốn session tự gia hạn khi người dùng còn hoạt động.",
        "request_type": "feature",
        **overrides,
    }
    return client.post("/client-requests", json=payload, headers=HEADERS)


def test_create_returns_context_with_citations(monkeypatch):
    client = _client(monkeypatch, [SPEC_MATCH])

    response = _create(client)

    assert response.status_code == 201
    body = response.json()
    assert body["request_id"].startswith("req-")
    context = body["context"]
    assert context["has_related_specs"] is True
    assert context["warning"] is None
    assert context["excerpts"][0]["source"] == "docs/imported/session-spec.md"
    assert context["excerpts"][0]["score"] is not None
    assert context["related_documents"][0]["excerpt_count"] == 1


def test_create_without_related_specs_warns_explicitly(monkeypatch):
    client = _client(monkeypatch, [])

    response = _create(client)

    assert response.status_code == 201
    context = response.json()["context"]
    assert context["has_related_specs"] is False
    assert "KHÔNG tìm thấy đặc tả" in context["warning"]


def test_create_rejects_unknown_request_type(monkeypatch):
    client = _client(monkeypatch, [SPEC_MATCH])

    response = _create(client, request_type="chore")

    assert response.status_code == 422


def test_context_markdown_per_role(monkeypatch):
    client = _client(monkeypatch, [SPEC_MATCH])
    request_id = _create(client).json()["request_id"]

    response = client.get(f"/client-requests/{request_id}/context", params={"role": "tester"}, headers=HEADERS)

    assert response.status_code == 200
    markdown = response.json()["markdown"]
    assert "[1] docs/imported/session-spec.md" in markdown
    assert "regression test" in markdown
    assert "Session của người dùng tồn tại tối đa 28 ngày." in markdown


def test_context_rejects_unknown_role(monkeypatch):
    client = _client(monkeypatch, [SPEC_MATCH])
    request_id = _create(client).json()["request_id"]

    response = client.get(f"/client-requests/{request_id}/context", params={"role": "designer"}, headers=HEADERS)

    assert response.status_code == 422


def test_get_unknown_request_returns_404(monkeypatch):
    client = _client(monkeypatch, [SPEC_MATCH])

    response = client.get("/client-requests/req-missing", headers=HEADERS)

    assert response.status_code == 404


def test_list_and_reanalyze(monkeypatch):
    client = _client(monkeypatch, [])
    request_id = _create(client).json()["request_id"]

    # Sau khi "ingest" thêm đặc tả, reanalyze phải tìm thấy trích đoạn mới.
    monkeypatch.setattr(main, "_retrieve", lambda query, limit, filters: ([SPEC_MATCH], {"mode": "hybrid"}))
    reanalyzed = client.post(f"/client-requests/{request_id}/reanalyze", headers=HEADERS)

    assert reanalyzed.status_code == 200
    assert reanalyzed.json()["context"]["has_related_specs"] is True

    listing = client.get("/client-requests", headers=HEADERS)
    assert listing.status_code == 200
    assert any(r["request_id"] == request_id for r in listing.json())


def test_markdown_no_specs_forbids_guessing():
    request = {
        "request_id": "req-x",
        "title": "T",
        "description": "D",
        "request_type": "bug",
        "project": None,
    }
    package = client_requests.build_context_package("T\nD", [], {"mode": "dense"})

    markdown = client_requests.render_context_markdown(request, package, "pm")

    assert "KHÔNG suy đoán" in markdown
    assert "không bịa" in markdown
