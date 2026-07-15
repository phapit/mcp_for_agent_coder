"""Stable Kafka job contracts for the knowledge pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class JobType(StrEnum):
    DOCUMENT_INGEST = "document.ingest"
    EXCEL_INGEST = "excel.ingest"
    SPREADSHEET_INGEST = "spreadsheet.ingest"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    RETRYING = "retrying"
    DEAD_LETTERED = "dead_lettered"


class JobEvent(BaseModel):
    schema_version: int = 1
    event_id: UUID
    job_id: UUID
    event_type: str
    job_type: JobType
    status: JobStatus
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    correlation_id: str
    attempt: int = Field(default=0, ge=0)
    payload: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None

