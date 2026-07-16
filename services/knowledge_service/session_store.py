"""MongoDB-backed conversation sessions so /answer can use multi-turn context."""

from __future__ import annotations

from datetime import datetime, timezone


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionStore:
    """One document per session_id, with a capped list of question/answer turns."""

    def __init__(self, collection, max_turns: int = 20):
        self.collection = collection
        self.max_turns = max_turns
        try:
            self.collection.create_index("session_id", unique=True)
            self.collection.create_index("updated_at")
        except Exception:
            pass  # best-effort; Mongo may be briefly unavailable

    def get_turns(self, session_id: str, limit: int) -> list[dict]:
        """Most recent turns, oldest first, each {"question": ..., "answer": ...}."""
        document = self.collection.find_one({"session_id": session_id}, {"_id": 0, "turns": 1})
        if not document:
            return []
        turns = document.get("turns") or []
        return turns[-limit:] if limit > 0 else []

    def append_turn(self, session_id: str, question: str, answer: str) -> None:
        now = _utc_now_iso()
        self.collection.update_one(
            {"session_id": session_id},
            {
                "$push": {
                    "turns": {
                        "$each": [{"question": question, "answer": answer, "at": now}],
                        "$slice": -self.max_turns,
                    }
                },
                "$set": {"updated_at": now},
                "$setOnInsert": {"created_at": now},
            },
            upsert=True,
        )

    def get_session(self, session_id: str) -> dict | None:
        return self.collection.find_one({"session_id": session_id}, {"_id": 0})

    def delete_session(self, session_id: str) -> bool:
        return self.collection.delete_one({"session_id": session_id}).deleted_count > 0


def history_messages(turns: list[dict]) -> list[dict]:
    """Convert stored turns into chat messages preceding the current question."""
    messages: list[dict] = []
    for turn in turns:
        messages.append({"role": "user", "content": turn["question"]})
        messages.append({"role": "assistant", "content": turn["answer"]})
    return messages
