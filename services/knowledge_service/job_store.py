"""Job state persistence abstraction.

The in-memory implementation is deliberately small for the first local phase;
the interface allows replacing it with MongoDB without changing API contracts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from typing import Any
from uuid import UUID

from job_contracts import JobStatus, JobType


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, dict[str, Any]] = {}
        self._lock = Lock()

    def create(self, job_id: UUID, job_type: JobType, correlation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        job = {
            "job_id": str(job_id),
            "job_type": job_type,
            "status": JobStatus.QUEUED,
            "correlation_id": correlation_id,
            "payload": payload,
            "attempt": 0,
            "created_at": now,
            "updated_at": now,
            "error": None,
        }
        with self._lock:
            self._jobs[str(job_id)] = job
        return job.copy()

    def get(self, job_id: UUID) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            return job.copy() if job else None

    def update(self, job_id: UUID, status: JobStatus, *, error: str | None = None, attempt: int | None = None) -> dict[str, Any] | None:
        with self._lock:
            job = self._jobs.get(str(job_id))
            if not job:
                return None
            job["status"] = status
            job["updated_at"] = datetime.now(timezone.utc).isoformat()
            job["error"] = error
            if attempt is not None:
                job["attempt"] = attempt
            return job.copy()


class MongoJobStore:
    """Cùng interface với JobStore nhưng bền qua restart: consumer/API đều tra được job."""

    def __init__(self, collection):
        self.collection = collection
        try:
            self.collection.create_index("job_id", unique=True)
            self.collection.create_index("status")
        except Exception:
            pass  # best-effort; Mongo có thể chưa sẵn sàng lúc khởi động

    def create(self, job_id: UUID, job_type: JobType, correlation_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(timezone.utc).isoformat()
        job = {
            "job_id": str(job_id),
            "job_type": str(job_type),
            "status": str(JobStatus.QUEUED),
            "correlation_id": correlation_id,
            "payload": payload,
            "attempt": 0,
            "created_at": now,
            "updated_at": now,
            "error": None,
        }
        self.collection.replace_one({"job_id": str(job_id)}, job, upsert=True)
        return dict(job)

    def get(self, job_id: UUID) -> dict[str, Any] | None:
        return self.collection.find_one({"job_id": str(job_id)}, {"_id": 0})

    def update(self, job_id: UUID, status: JobStatus, *, error: str | None = None, attempt: int | None = None) -> dict[str, Any] | None:
        fields: dict[str, Any] = {
            "status": str(status),
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "error": error,
        }
        if attempt is not None:
            fields["attempt"] = attempt
        result = self.collection.find_one_and_update(
            {"job_id": str(job_id)}, {"$set": fields}, projection={"_id": 0}, return_document=True
        )
        return result
