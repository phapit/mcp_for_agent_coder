"""Đồng bộ /ingest với Qdrant: ID ổn định, skip theo content_hash, xóa file đã mất."""
import uuid

import pytest
from fastapi.testclient import TestClient

import main


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    def embed_query(self, text):
        return [0.1, 0.2, 0.3]


class FakeQdrant:
    """Mô phỏng tối thiểu các API Qdrant mà /ingest sử dụng, lưu point trong dict."""

    def __init__(self):
        self.points: dict[str, dict] = {}
        self.collection_created = False

    # --- collection APIs ---
    def get_collections(self):
        class _Desc:
            def __init__(self, name):
                self.name = name

        class _Result:
            def __init__(self, names):
                self.collections = [_Desc(n) for n in names]

        return _Result([main.COLLECTION_NAME] if self.collection_created else [])

    def create_collection(self, collection_name, vectors_config):
        self.collection_created = True

    def create_payload_index(self, collection_name, field_name, field_schema):
        pass

    # --- point APIs ---
    def upsert(self, collection_name, points):
        for p in points:
            self.points[str(p.id)] = dict(p.payload)

    def _matches(self, payload, condition):
        value = payload.get(condition.key)
        match = condition.match
        if hasattr(match, "any") and match.any is not None:
            return value in match.any
        return value == match.value

    def _filter_ids(self, points_filter):
        ids = []
        for pid, payload in self.points.items():
            must = all(self._matches(payload, c) for c in (points_filter.must or []))
            must_not = any(self._matches(payload, c) for c in (points_filter.must_not or []))
            if must and not must_not:
                ids.append(pid)
        return ids

    def count(self, collection_name, count_filter, exact):
        class _Count:
            def __init__(self, n):
                self.count = n

        return _Count(len(self._filter_ids(count_filter)))

    def delete(self, collection_name, points_selector):
        for pid in self._filter_ids(points_selector.filter):
            del self.points[pid]

    def scroll(self, collection_name, scroll_filter, limit, with_payload, with_vectors):
        class _Point:
            def __init__(self, payload):
                self.payload = payload

        ids = self._filter_ids(scroll_filter)[:limit]
        return [_Point(self.points[i]) for i in ids], None

    def query_points(self, collection_name, query, limit, query_filter=None):
        class _Point:
            def __init__(self, payload):
                self.payload = payload
                self.score = 1.0

        class _Result:
            def __init__(self, points):
                self.points = points

        ids = self._filter_ids(query_filter) if query_filter is not None else list(self.points)
        return _Result([_Point(self.points[i]) for i in ids[:limit]])


class FakeMongoCollection:
    """Đủ tối thiểu cho DocumentRegistry: find_one/update_one/update_many/find."""

    def __init__(self):
        self.docs: dict[str, dict] = {}

    def create_index(self, *args, **kwargs):
        pass

    @staticmethod
    def _matches(doc, query):
        for key, expected in query.items():
            value = doc.get(key)
            if isinstance(expected, dict):
                if "$nin" in expected and value in expected["$nin"]:
                    return False
                if "$ne" in expected and value == expected["$ne"]:
                    return False
            elif value != expected:
                return False
        return True

    def find_one(self, query, projection=None):
        for doc in self.docs.values():
            if self._matches(doc, query):
                return {k: v for k, v in doc.items() if k != "_id"}
        return None

    def update_one(self, query, update, upsert=False):
        for doc in self.docs.values():
            if self._matches(doc, query):
                doc.update(update["$set"])
                return
        if upsert:
            new_doc = dict(query)
            new_doc.update(update["$set"])
            self.docs[new_doc["document_id"]] = new_doc

    def update_many(self, query, update):
        class _Result:
            def __init__(self, n):
                self.modified_count = n

        modified = 0
        for doc in self.docs.values():
            if self._matches(doc, query):
                doc.update(update["$set"])
                modified += 1
        return _Result(modified)

    def find(self, query, projection=None):
        return [
            {k: v for k, v in doc.items() if k != "_id"}
            for doc in self.docs.values()
            if self._matches(doc, query)
        ]


@pytest.fixture
def client(monkeypatch, tmp_path):
    from document_registry import DocumentRegistry

    fake_qdrant = FakeQdrant()
    registry = DocumentRegistry(FakeMongoCollection(), max_attempts=3)
    monkeypatch.setattr(main, "SERVICE_API_KEY", "shared-secret")
    monkeypatch.setattr(main, "qdrant_client", fake_qdrant)
    monkeypatch.setattr(main, "embeddings", FakeEmbeddings())
    monkeypatch.setattr(main, "document_registry", registry)
    monkeypatch.setattr(main, "DOCS_GLOB", str(tmp_path / "**/*.md"))
    main._rate_buckets.clear()
    return TestClient(main.app), fake_qdrant, tmp_path


def _ingest(test_client, **body):
    return test_client.post("/ingest", json=body or None, headers={"X-API-Key": "shared-secret"})


def test_ingest_writes_full_payload(client):
    test_client, fake_qdrant, tmp_path = client
    (tmp_path / "a.md").write_text("# Doc A\nnoi dung", encoding="utf-8")

    response = _ingest(test_client)

    assert response.status_code == 200
    assert len(response.json()["ingested"]) == 1
    payload = next(iter(fake_qdrant.points.values()))
    for field in ("text", "source", "document_id", "content_hash", "version", "ingested_at", "chunk_index"):
        assert field in payload
    assert payload["version"] == 1
    # Point ID phải là UUID hợp lệ (Qdrant không nhận sha256 hex).
    uuid.UUID(next(iter(fake_qdrant.points)))


def test_unchanged_file_is_skipped_and_reingest_bumps_version(client):
    test_client, fake_qdrant, tmp_path = client
    doc = tmp_path / "a.md"
    doc.write_text("# Doc A\nnoi dung", encoding="utf-8")

    _ingest(test_client)
    second = _ingest(test_client).json()
    assert len(second["skipped"]) == 1 and not second["ingested"]

    doc.write_text("# Doc A\nnoi dung moi", encoding="utf-8")
    third = _ingest(test_client).json()
    assert len(third["ingested"]) == 1
    payload = next(iter(fake_qdrant.points.values()))
    assert payload["version"] == 2
    # Chunk của phiên bản cũ phải bị xóa, không còn dữ liệu cũ lẫn mới.
    hashes = {p["content_hash"] for p in fake_qdrant.points.values()}
    assert len(hashes) == 1


def test_deleted_file_is_pruned(client):
    test_client, fake_qdrant, tmp_path = client
    keep = tmp_path / "keep.md"
    gone = tmp_path / "gone.md"
    keep.write_text("# Keep", encoding="utf-8")
    gone.write_text("# Gone", encoding="utf-8")

    _ingest(test_client)
    assert len({p["document_id"] for p in fake_qdrant.points.values()}) == 2

    gone.unlink()
    response = _ingest(test_client).json()

    assert response["pruned_points"] >= 1
    remaining_sources = {p["source"] for p in fake_qdrant.points.values()}
    assert remaining_sources == {str(keep)}


def test_ingest_status_endpoint(client):
    test_client, _, tmp_path = client
    (tmp_path / "a.md").write_text("# Doc A", encoding="utf-8")

    _ingest(test_client)
    response = test_client.get("/ingest/status", headers={"X-API-Key": "shared-secret"})

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "completed"
    assert body["total_files"] == 1


def test_registry_records_ingested_document(client):
    test_client, _, tmp_path = client
    (tmp_path / "proj_a" / "a.md").parent.mkdir()
    (tmp_path / "proj_a" / "a.md").write_text("# Doc A", encoding="utf-8")

    _ingest(test_client)

    entries = main.document_registry.list_by_status("ingested")
    assert len(entries) == 1
    assert entries[0]["version"] == 1
    assert entries[0]["metadata"]["project"] == "proj_a"
    assert entries[0]["metadata"]["document_type"] == "md"


def test_failed_document_moves_to_dead_letter_after_max_attempts(client, monkeypatch):
    test_client, _, tmp_path = client
    (tmp_path / "bad.md").write_text("# Bad", encoding="utf-8")

    class BrokenEmbeddings:
        def embed_documents(self, texts):
            raise RuntimeError("embedding blew up")

    monkeypatch.setattr(main, "embeddings", BrokenEmbeddings())

    for expected_attempts in (1, 2, 3):
        body = _ingest(test_client, force=True).json()
        assert body["failed"][0]["attempts"] == expected_attempts

    dead = test_client.get("/ingest/dead-letter", headers={"X-API-Key": "shared-secret"}).json()
    assert len(dead) == 1 and dead[0]["status"] == "dead_letter"

    # Lần chạy tiếp theo (không force): file dead-letter bị bỏ qua, không retry.
    body = _ingest(test_client).json()
    assert len(body["dead_lettered"]) == 1 and not body["failed"]

    # Requeue rồi sửa embeddings: file được ingest lại thành công.
    requeued = test_client.post(
        "/ingest/dead-letter/requeue", headers={"X-API-Key": "shared-secret"}
    ).json()
    assert requeued["requeued"] == 1
    monkeypatch.setattr(main, "embeddings", FakeEmbeddings())
    body = _ingest(test_client).json()
    assert len(body["ingested"]) == 1
    assert main.document_registry.list_by_status("dead_letter") == []


def test_background_ingest_returns_202(client):
    test_client, _, tmp_path = client
    (tmp_path / "a.md").write_text("# Doc A", encoding="utf-8")

    response = _ingest(test_client, background=True)

    assert response.status_code == 202
    assert response.json()["status"] == "started"
    # Chờ worker hoàn tất (embedding giả nên rất nhanh).
    import time as _time

    for _ in range(50):
        status = test_client.get("/ingest/status", headers={"X-API-Key": "shared-secret"}).json()
        if status.get("status") not in ("running", "started"):
            break
        _time.sleep(0.1)
    assert status["status"] == "completed"
    assert len(status["ingested"]) == 1


def test_search_respects_metadata_filters(client):
    test_client, _, tmp_path = client
    (tmp_path / "proj_a").mkdir()
    (tmp_path / "proj_b").mkdir()
    (tmp_path / "proj_a" / "a.md").write_text("# Doc A", encoding="utf-8")
    (tmp_path / "proj_b" / "b.md").write_text("# Doc B", encoding="utf-8")
    _ingest(test_client)

    headers = {"X-API-Key": "shared-secret"}
    everything = test_client.post("/search", json={"query": "doc", "limit": 10}, headers=headers).json()
    assert len(everything) == 2

    only_a = test_client.post(
        "/search",
        json={"query": "doc", "limit": 10, "filters": {"project": "proj_a"}},
        headers=headers,
    ).json()
    assert len(only_a) == 1
    assert "proj_a" in only_a[0]["source"]

    nothing = test_client.post(
        "/search",
        json={"query": "doc", "limit": 10, "filters": {"environment": "production"}},
        headers=headers,
    ).json()
    assert nothing == []
