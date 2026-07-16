"""MongoDB-backed registry tracking the ingestion state of every document."""

from __future__ import annotations

from datetime import datetime, timezone

STATUS_INGESTED = "ingested"
STATUS_FAILED = "failed"
STATUS_DEAD_LETTER = "dead_letter"
STATUS_REMOVED = "removed"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class DocumentRegistry:
    """One record per document_id: source, content_hash, version, status, attempts, error."""

    def __init__(self, collection, max_attempts: int = 3):
        self.collection = collection
        self.max_attempts = max_attempts
        try:
            self.collection.create_index("document_id", unique=True)
            self.collection.create_index("status")
        except Exception:
            pass  # index creation is best-effort; Mongo may be briefly unavailable

    def get(self, document_id: str) -> dict | None:
        return self.collection.find_one({"document_id": document_id}, {"_id": 0})

    def record_ingested(
        self,
        document_id: str,
        *,
        source: str,
        content_hash: str,
        version: int,
        chunks: int,
        metadata: dict | None = None,
    ) -> None:
        self.collection.update_one(
            {"document_id": document_id},
            {
                "$set": {
                    "source": source,
                    "content_hash": content_hash,
                    "version": version,
                    "chunks": chunks,
                    "status": STATUS_INGESTED,
                    "attempts": 0,
                    "error": None,
                    "metadata": metadata or {},
                    "ingested_at": _utc_now_iso(),
                    "updated_at": _utc_now_iso(),
                }
            },
            upsert=True,
        )

    def record_failure(self, document_id: str, *, source: str, content_hash: str, error: str) -> dict:
        """Increment attempts; move to dead_letter once max_attempts is reached.

        Attempts are counted per content_hash: a failing document that has been
        edited since gets a fresh budget of retries.
        """
        entry = self.get(document_id)
        previous_attempts = 0
        if entry and entry.get("failed_content_hash") == content_hash:
            previous_attempts = int(entry.get("attempts") or 0)
        attempts = previous_attempts + 1
        status = STATUS_DEAD_LETTER if attempts >= self.max_attempts else STATUS_FAILED
        self.collection.update_one(
            {"document_id": document_id},
            {
                "$set": {
                    "source": source,
                    "failed_content_hash": content_hash,
                    "status": status,
                    "attempts": attempts,
                    "error": error,
                    "updated_at": _utc_now_iso(),
                }
            },
            upsert=True,
        )
        return {"status": status, "attempts": attempts}

    def is_dead_lettered(self, document_id: str, content_hash: str) -> bool:
        entry = self.get(document_id)
        return (
            entry is not None
            and entry.get("status") == STATUS_DEAD_LETTER
            and entry.get("failed_content_hash") == content_hash
        )

    def mark_removed_except(self, active_document_ids: list[str]) -> int:
        result = self.collection.update_many(
            {"document_id": {"$nin": active_document_ids}, "status": {"$ne": STATUS_REMOVED}},
            {"$set": {"status": STATUS_REMOVED, "updated_at": _utc_now_iso()}},
        )
        return result.modified_count

    def list_by_status(self, status: str) -> list[dict]:
        return list(self.collection.find({"status": status}, {"_id": 0}))

    def requeue(self, document_id: str | None = None) -> int:
        """Reset dead-lettered documents so the next ingest run retries them."""
        query: dict = {"status": STATUS_DEAD_LETTER}
        if document_id:
            query["document_id"] = document_id
        result = self.collection.update_many(
            query,
            {
                "$set": {
                    "status": STATUS_FAILED,
                    "attempts": 0,
                    "updated_at": _utc_now_iso(),
                }
            },
        )
        return result.modified_count
