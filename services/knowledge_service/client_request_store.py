"""MongoDB store cho yêu cầu từ khách hàng (client requests)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ClientRequestStore:
    """Một document cho mỗi yêu cầu, kèm gói ngữ cảnh phân tích gần nhất."""

    def __init__(self, collection):
        self.collection = collection
        try:
            self.collection.create_index("request_id", unique=True)
            self.collection.create_index("created_at")
        except Exception:
            pass  # best-effort; Mongo may be briefly unavailable

    def create(
        self,
        title: str,
        description: str,
        request_type: str,
        project: str | None = None,
        requester: str | None = None,
    ) -> dict:
        now = _utc_now_iso()
        record = {
            "request_id": f"req-{uuid.uuid4().hex[:12]}",
            "title": title,
            "description": description,
            "request_type": request_type,
            "project": project,
            "requester": requester,
            "status": "new",
            "created_at": now,
            "updated_at": now,
            "context": None,
        }
        self.collection.insert_one({**record})
        return record

    def list(self, limit: int = 50) -> list[dict]:
        """Danh sách rút gọn, mới nhất trước (không kèm nội dung trích đoạn)."""
        cursor = (
            self.collection.find({}, {"_id": 0, "description": 0, "context.excerpts": 0})
            .sort("created_at", -1)
            .limit(limit)
        )
        return list(cursor)

    def get(self, request_id: str) -> dict | None:
        return self.collection.find_one({"request_id": request_id}, {"_id": 0})

    def save_context(self, request_id: str, package: dict) -> bool:
        result = self.collection.update_one(
            {"request_id": request_id},
            {"$set": {"context": package, "updated_at": _utc_now_iso()}},
        )
        return result.matched_count > 0
