from uuid import uuid4

from job_contracts import JobEvent, JobStatus, JobType
from job_store import JobStore


def test_job_event_is_versioned_and_serializable():
    event = JobEvent(
        event_id=uuid4(),
        job_id=uuid4(),
        event_type="document.ingest.requested",
        job_type=JobType.DOCUMENT_INGEST,
        status=JobStatus.QUEUED,
        correlation_id="request-1",
    )
    data = event.model_dump(mode="json")
    assert data["schema_version"] == 1
    assert data["job_type"] == "document.ingest"


def test_job_store_update_is_idempotent_for_unknown_job():
    store = JobStore()
    job_id = uuid4()
    assert store.get(job_id) is None
    assert store.update(job_id, JobStatus.RUNNING) is None

