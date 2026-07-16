from ingest_history import summarize_run
from session_store import SessionStore, history_messages


class FakeDeleteResult:
    def __init__(self, deleted_count):
        self.deleted_count = deleted_count


class FakeSessionCollection:
    def __init__(self):
        self.documents = {}

    def create_index(self, *args, **kwargs):
        pass

    def find_one(self, filter, projection=None):
        document = self.documents.get(filter["session_id"])
        if document is None:
            return None
        if projection and "_id" in projection and projection["_id"] == 0:
            document = {k: v for k, v in document.items() if k != "_id"}
        if projection:
            keep = {k for k, v in projection.items() if v == 1}
            if keep:
                document = {k: v for k, v in document.items() if k in keep}
        return dict(document)

    def update_one(self, filter, update, upsert=False):
        key = filter["session_id"]
        document = self.documents.setdefault(key, {"session_id": key, "turns": []})
        for field, value in update.get("$setOnInsert", {}).items():
            document.setdefault(field, value)
        document.update(update.get("$set", {}))
        push = update.get("$push", {}).get("turns")
        if push:
            document["turns"].extend(push["$each"])
            slice_n = push.get("$slice")
            if slice_n is not None and slice_n < 0:
                document["turns"] = document["turns"][slice_n:]

    def delete_one(self, filter):
        deleted = 1 if filter["session_id"] in self.documents else 0
        self.documents.pop(filter["session_id"], None)
        return FakeDeleteResult(deleted)


def test_append_and_get_turns_ordering():
    store = SessionStore(FakeSessionCollection(), max_turns=10)
    store.append_turn("s1", "câu hỏi 1", "trả lời 1")
    store.append_turn("s1", "câu hỏi 2", "trả lời 2")

    turns = store.get_turns("s1", limit=5)
    assert [t["question"] for t in turns] == ["câu hỏi 1", "câu hỏi 2"]

    last_only = store.get_turns("s1", limit=1)
    assert [t["question"] for t in last_only] == ["câu hỏi 2"]


def test_max_turns_cap():
    store = SessionStore(FakeSessionCollection(), max_turns=2)
    for i in range(5):
        store.append_turn("s1", f"q{i}", f"a{i}")
    turns = store.get_turns("s1", limit=10)
    assert [t["question"] for t in turns] == ["q3", "q4"]


def test_history_messages_alternates_roles():
    messages = history_messages([{"question": "q1", "answer": "a1"}, {"question": "q2", "answer": "a2"}])
    assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant"]
    assert messages[0]["content"] == "q1"


def test_delete_session():
    store = SessionStore(FakeSessionCollection())
    store.append_turn("s1", "q", "a")
    assert store.delete_session("s1") is True
    assert store.delete_session("s1") is False
    assert store.get_turns("s1", limit=5) == []


def test_summarize_run_compacts_lists():
    summary = {
        "status": "completed_with_errors",
        "started_at": "2026-07-16T00:00:00+00:00",
        "finished_at": "2026-07-16T00:01:00+00:00",
        "total_files": 3,
        "ingested": [{"file": "a.md"}, {"file": "b.md"}],
        "skipped": [],
        "failed": [{"file": "c.md", "error": "boom", "chunks": 0}],
        "dead_lettered": [],
        "pruned_points": 4,
    }
    record = summarize_run(summary, trigger="excel_export")

    assert record["trigger"] == "excel_export"
    assert record["ingested_count"] == 2
    assert record["failed_count"] == 1
    assert record["failures"] == [{"file": "c.md", "error": "boom"}]
    assert "ingested" not in record  # full per-file lists are not persisted
    assert record["run_id"]
