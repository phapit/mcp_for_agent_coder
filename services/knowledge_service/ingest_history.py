"""MongoDB-backed history of ingest runs, queryable via /ingest/history."""

from __future__ import annotations

import uuid

# Per-file result lists can be huge; the history keeps counts plus failures only.
_LIST_FIELDS = ("ingested", "skipped", "failed", "dead_lettered")


def summarize_run(summary: dict, *, trigger: str) -> dict:
    """Compact a full ingest summary into a history record."""
    record = {
        "run_id": str(uuid.uuid4()),
        "trigger": trigger,
        "status": summary.get("status"),
        "started_at": summary.get("started_at"),
        "finished_at": summary.get("finished_at"),
        "total_files": summary.get("total_files"),
        "pruned_points": summary.get("pruned_points", 0),
        "error": summary.get("error"),
    }
    for field in _LIST_FIELDS:
        items = summary.get(field) or []
        record[f"{field}_count"] = len(items)
    # Keep failure details: they are what operators come back to inspect.
    record["failures"] = [
        {"file": item.get("file"), "error": item.get("error")} for item in summary.get("failed") or []
    ]
    return record


class IngestHistory:
    def __init__(self, collection, max_records: int = 200):
        self.collection = collection
        self.max_records = max_records
        try:
            self.collection.create_index("started_at")
        except Exception:
            pass  # best-effort; Mongo may be briefly unavailable

    def record(self, summary: dict, *, trigger: str = "manual") -> dict:
        record = summarize_run(summary, trigger=trigger)
        self.collection.insert_one(dict(record))
        self._prune()
        return record

    def _prune(self) -> None:
        try:
            total = self.collection.count_documents({})
            if total > self.max_records:
                cutoff = list(
                    self.collection.find({}, {"started_at": 1})
                    .sort("started_at", -1)
                    .skip(self.max_records)
                    .limit(1)
                )
                if cutoff:
                    self.collection.delete_many({"started_at": {"$lte": cutoff[0]["started_at"]}})
        except Exception:
            pass  # history pruning must never break an ingest run

    def list_runs(self, limit: int = 20) -> list[dict]:
        return list(self.collection.find({}, {"_id": 0}).sort("started_at", -1).limit(limit))
