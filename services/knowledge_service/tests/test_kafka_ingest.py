"""Event-driven ingest qua Kafka: enqueue 202, worker xử lý, retry/DLQ."""
import uuid

import pytest
from fastapi.testclient import TestClient

import ingest_worker as ingest_worker_module
import kafka_bus
import main
from job_contracts import JobStatus
from job_store import JobStore


class FakeBus:
    def __init__(self):
        self.published: list[tuple[str, object]] = []
        self.fail = False

    def publish_event(self, topic, event):
        if self.fail:
            raise kafka_bus.KafkaBusError("kafka down")
        self.published.append((topic, event))

    def topics(self):
        return [topic for topic, _ in self.published]


@pytest.fixture
def worker_env():
    bus = FakeBus()
    store = JobStore()
    return bus, store


def _request_event(payload=None, attempt=0):
    event = ingest_worker_module.new_request_event(
        correlation_id="corr-1", payload=payload or {"force": False, "prune": True, "trigger": "manual"}
    )
    return event.model_copy(update={"attempt": attempt})


def test_worker_success_publishes_completed(worker_env):
    bus, store = worker_env
    event = _request_event()
    store.create(event.job_id, event.job_type, event.correlation_id, event.payload)
    worker = ingest_worker_module.IngestWorker(
        bus, store, lambda payload: {"status": "completed", "total_files": 2, "failed": []}
    )

    outcome = worker.handle_event(event)

    assert outcome == "completed"
    assert store.get(event.job_id)["status"] == JobStatus.SUCCEEDED
    assert bus.topics() == [kafka_bus.TOPIC_COMPLETED]


def test_worker_failure_publishes_failed_and_retry(worker_env):
    bus, store = worker_env
    event = _request_event()
    store.create(event.job_id, event.job_type, event.correlation_id, event.payload)

    def boom(payload):
        raise RuntimeError("qdrant down")

    worker = ingest_worker_module.IngestWorker(bus, store, boom)

    outcome = worker.handle_event(event)

    assert outcome == "retried"
    job = store.get(event.job_id)
    assert job["status"] == JobStatus.RETRYING
    assert job["attempt"] == 1
    assert bus.topics() == [kafka_bus.TOPIC_FAILED, kafka_bus.TOPIC_RETRY]
    retry_event = bus.published[-1][1]
    assert retry_event.attempt == 1
    assert "next_attempt_at" in retry_event.payload


def test_worker_dead_letters_after_max_attempts(worker_env):
    bus, store = worker_env
    event = _request_event(attempt=kafka_bus.RETRY_MAX_ATTEMPTS - 1)
    store.create(event.job_id, event.job_type, event.correlation_id, event.payload)

    def boom(payload):
        raise RuntimeError("still broken")

    worker = ingest_worker_module.IngestWorker(bus, store, boom)

    outcome = worker.handle_event(event)

    assert outcome == "dead_lettered"
    assert store.get(event.job_id)["status"] == JobStatus.DEAD_LETTERED
    assert bus.topics() == [kafka_bus.TOPIC_FAILED, kafka_bus.TOPIC_DLQ]


def _api_client(monkeypatch, tmp_path, bus):
    monkeypatch.setattr(main, "SERVICE_API_KEY", "shared-secret")
    main._rate_buckets.clear()
    (tmp_path / "a.md").write_text("# Doc A", encoding="utf-8")
    monkeypatch.setattr(main, "DOCS_GLOB", str(tmp_path / "**/*.md"))
    monkeypatch.setattr(main, "embeddings", object())
    monkeypatch.setattr(main, "qdrant_client", object())
    monkeypatch.setattr(main.kafka_bus, "KAFKA_ENABLED", True)
    monkeypatch.setattr(main, "kafka_bus_instance", bus)
    monkeypatch.setattr(main, "job_store", JobStore())
    return TestClient(main.app)


def test_ingest_enqueues_job_and_returns_202(monkeypatch, tmp_path):
    bus = FakeBus()
    client = _api_client(monkeypatch, tmp_path, bus)
    headers = {"X-API-Key": "shared-secret"}

    response = client.post("/ingest", json={"force": True}, headers=headers)

    assert response.status_code == 202
    body = response.json()
    assert body["status"] == "queued"
    assert bus.topics() == [kafka_bus.TOPIC_REQUESTED]
    published = bus.published[0][1]
    assert published.payload["force"] is True

    job = client.get(f"/ingest/jobs/{body['job_id']}", headers=headers)
    assert job.status_code == 200
    assert job.json()["status"] == JobStatus.QUEUED


def test_ingest_returns_503_when_kafka_unavailable(monkeypatch, tmp_path):
    bus = FakeBus()
    bus.fail = True
    client = _api_client(monkeypatch, tmp_path, bus)

    response = client.post("/ingest", json={}, headers={"X-API-Key": "shared-secret"})

    assert response.status_code == 503


def test_ingest_job_endpoint_validates_uuid(monkeypatch, tmp_path):
    client = _api_client(monkeypatch, tmp_path, FakeBus())
    headers = {"X-API-Key": "shared-secret"}

    assert client.get("/ingest/jobs/not-a-uuid", headers=headers).status_code == 422
    assert client.get(f"/ingest/jobs/{uuid.uuid4()}", headers=headers).status_code == 404
