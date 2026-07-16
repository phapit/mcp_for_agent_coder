"""Pipeline đồng bộ Markdown → Qdrant + các endpoint /ingest*.

State (clients, config) sống ở main.py (composition root); mọi truy cập đều
qua `main.<attr>` tại thời điểm request để test có thể monkeypatch trên main.
Lock/trạng thái riêng của pipeline (ingest_status, run lock) sống tại đây.
"""

from __future__ import annotations

import glob
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    TextIndexParams,
    TokenizerType,
    VectorParams,
)

import chunking
import document_identity as identity
import ingest_worker as ingest_worker_module
import kafka_bus
import observability
from document_registry import STATUS_DEAD_LETTER, STATUS_FAILED, DocumentRegistry
from schemas import IngestRequest

import main

logger = logging.getLogger(__name__)
router = APIRouter()

_ingest_status_lock = threading.Lock()
_last_ingest_status: dict = {"status": "never_run"}
_ingest_run_lock = threading.Lock()


def _set_ingest_status(**fields) -> dict:
    with _ingest_status_lock:
        _last_ingest_status.clear()
        _last_ingest_status.update(fields)
        return dict(_last_ingest_status)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _point_uuid(chunk_hash: str) -> str:
    """Qdrant point IDs must be UUIDs or unsigned ints; fold the sha256 chunk hash into a UUID."""
    return str(uuid.UUID(chunk_hash[:32]))


def _collection_exists() -> bool:
    return main.COLLECTION_NAME in [c.name for c in main.qdrant_client.get_collections().collections]


def _ensure_collection(vector_size: int):
    existing = [c.name for c in main.qdrant_client.get_collections().collections]
    if main.COLLECTION_NAME not in existing:
        main.qdrant_client.create_collection(
            collection_name=main.COLLECTION_NAME,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def _ensure_payload_indexes():
    keyword_fields = ("document_id", "source", "content_hash", "project", "environment", "document_type")
    for field in keyword_fields:
        try:
            main.qdrant_client.create_payload_index(
                collection_name=main.COLLECTION_NAME,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass  # index already exists
    try:
        main.qdrant_client.create_payload_index(
            collection_name=main.COLLECTION_NAME,
            field_name="version",
            field_schema=PayloadSchemaType.INTEGER,
        )
    except Exception:
        pass
    try:
        # Full-text index over chunk text: powers the keyword half of hybrid search.
        main.qdrant_client.create_payload_index(
            collection_name=main.COLLECTION_NAME,
            field_name="text",
            field_schema=TextIndexParams(
                type="text",
                tokenizer=TokenizerType.WORD,
                lowercase=True,
                min_token_len=2,
            ),
        )
    except Exception:
        pass


def _document_metadata(file_path: str) -> dict:
    """Derive filterable metadata from the file location: project = first folder under the docs root."""
    docs_root = main.DOCS_GLOB.split("*", 1)[0].rstrip("/")
    try:
        parts = Path(os.path.relpath(file_path, docs_root)).parts
    except ValueError:
        parts = ()
    project = parts[0] if len(parts) > 1 else "default"
    return {
        "project": project,
        "environment": main.ENVIRONMENT,
        "document_type": Path(file_path).suffix.lstrip(".").lower() or "unknown",
    }


def _document_filter(doc_id: str) -> Filter:
    return Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))])


def _existing_document_state(doc_id: str) -> tuple[str | None, int]:
    """Return (content_hash, version) of the currently indexed document, if any."""
    points, _ = main.qdrant_client.scroll(
        collection_name=main.COLLECTION_NAME,
        scroll_filter=_document_filter(doc_id),
        limit=1,
        with_payload=["content_hash", "version"],
        with_vectors=False,
    )
    if not points:
        return None, 0
    payload = points[0].payload or {}
    return payload.get("content_hash"), int(payload.get("version") or 0)


def _delete_by_filter(points_filter: Filter) -> int:
    deleted = main.qdrant_client.count(
        collection_name=main.COLLECTION_NAME, count_filter=points_filter, exact=True
    ).count
    if deleted:
        main.qdrant_client.delete(
            collection_name=main.COLLECTION_NAME,
            points_selector=FilterSelector(filter=points_filter),
        )
    return deleted


def _sync_document(file_path: str, force: bool, collection_ready: bool) -> tuple[dict, bool]:
    """Upsert one markdown file into Qdrant, replacing chunks of any previous version."""
    raw = Path(file_path).read_bytes()
    text = raw.decode("utf-8", errors="replace")
    doc_id = identity.document_id(file_path)
    new_hash = identity.content_hash(raw)

    old_hash, old_version = (None, 0)
    if collection_ready:
        old_hash, old_version = _existing_document_state(doc_id)

    if old_hash == new_hash and not force:
        return {
            "file": file_path,
            "document_id": doc_id,
            "action": "skipped",
            "content_hash": new_hash,
            "version": old_version,
        }, collection_ready

    chunks = chunking.split_markdown(text, chunk_size=main.CHUNK_SIZE, chunk_overlap=main.CHUNK_OVERLAP)
    if not chunks:
        deleted = _delete_by_filter(_document_filter(doc_id)) if collection_ready else 0
        return {
            "file": file_path,
            "document_id": doc_id,
            "action": "emptied",
            "deleted_points": deleted,
        }, collection_ready

    vectors = main.embeddings.embed_documents([chunk.text for chunk in chunks])
    if not collection_ready:
        _ensure_collection(len(vectors[0]))
        collection_ready = True
    _ensure_payload_indexes()

    version = old_version + 1
    ingested_at = _utc_now_iso()
    metadata = _document_metadata(file_path)
    main.qdrant_client.upsert(
        collection_name=main.COLLECTION_NAME,
        points=[
            PointStruct(
                id=_point_uuid(identity.chunk_id(doc_id, index, chunk.text)),
                vector=vector,
                payload={
                    "text": chunk.text,
                    "source": file_path,
                    "document_id": doc_id,
                    "content_hash": new_hash,
                    "version": version,
                    "ingested_at": ingested_at,
                    "chunk_index": index,
                    "heading": chunk.heading,
                    "start_line": chunk.start_line,
                    "end_line": chunk.end_line,
                    **metadata,
                },
            )
            for index, (chunk, vector) in enumerate(zip(chunks, vectors))
        ],
    )

    # Drop chunks left over from the previous version of this document.
    stale_filter = Filter(
        must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))],
        must_not=[FieldCondition(key="content_hash", match=MatchValue(value=new_hash))],
    )
    deleted = _delete_by_filter(stale_filter)

    return {
        "file": file_path,
        "document_id": doc_id,
        "action": "ingested",
        "chunks": len(chunks),
        "version": version,
        "content_hash": new_hash,
        "metadata": metadata,
        "deleted_stale_points": deleted,
    }, collection_ready


def _record_ingest_history(summary: dict, trigger: str) -> None:
    if main.ingest_history is None:
        return
    try:
        main.ingest_history.record(summary, trigger=trigger)
    except Exception as e:
        logger.error(f"Failed to record ingest history: {e}", exc_info=True)


def _run_ingest(files: list[str], request: IngestRequest, trigger: str = "manual") -> dict:
    """Synchronize files with Qdrant, keeping the document registry up to date.

    Caller must hold _ingest_run_lock; it is released here when the run finishes.
    """
    started_at = _utc_now_iso()
    _set_ingest_status(status="running", started_at=started_at)

    ingested, skipped, failed, dead_lettered = [], [], [], []
    current_doc_ids = []
    try:
        collection_ready = _collection_exists()
        for file_path in files:
            doc_id = identity.document_id(file_path)
            current_doc_ids.append(doc_id)
            try:
                file_hash = identity.content_hash(Path(file_path).read_bytes())
            except OSError as e:
                logger.error(f"Cannot read '{file_path}': {e}")
                failed.append({"file": file_path, "document_id": doc_id, "error": str(e)})
                continue

            if (
                not request.force
                and main.document_registry is not None
                and main.document_registry.is_dead_lettered(doc_id, file_hash)
            ):
                dead_lettered.append({"file": file_path, "document_id": doc_id})
                continue

            try:
                result, collection_ready = _sync_document(file_path, request.force, collection_ready)
            except Exception as e:
                logger.error(f"Failed to ingest '{file_path}': {e}", exc_info=True)
                failure = {"file": file_path, "document_id": doc_id, "error": str(e)}
                if main.document_registry is not None:
                    failure.update(
                        main.document_registry.record_failure(
                            doc_id, source=file_path, content_hash=file_hash, error=str(e)
                        )
                    )
                failed.append(failure)
                continue

            (skipped if result["action"] == "skipped" else ingested).append(result)
            if main.document_registry is not None and result["action"] != "skipped":
                main.document_registry.record_ingested(
                    doc_id,
                    source=file_path,
                    content_hash=result.get("content_hash", file_hash),
                    version=result.get("version", 0),
                    chunks=result.get("chunks", 0),
                    metadata=result.get("metadata"),
                )

        pruned_points = 0
        if request.prune and collection_ready:
            # Removes documents whose files were deleted, plus legacy points without document_id.
            orphan_filter = Filter(
                must_not=[FieldCondition(key="document_id", match=MatchAny(any=current_doc_ids))]
            )
            pruned_points = _delete_by_filter(orphan_filter)
            if main.document_registry is not None:
                main.document_registry.mark_removed_except(current_doc_ids)
    except Exception as e:
        failure = {
            "status": "failed",
            "started_at": started_at,
            "finished_at": _utc_now_iso(),
            "error": str(e),
        }
        _set_ingest_status(**failure)
        _record_ingest_history(failure, trigger)
        raise
    finally:
        _ingest_run_lock.release()

    summary = {
        "status": "completed" if not failed else "completed_with_errors",
        "started_at": started_at,
        "finished_at": _utc_now_iso(),
        "total_files": len(files),
        "ingested": ingested,
        "skipped": skipped,
        "failed": failed,
        "dead_lettered": dead_lettered,
        "pruned_points": pruned_points,
    }
    _set_ingest_status(**summary)
    _record_ingest_history(summary, trigger)
    logger.info(
        "ingest_run_completed",
        extra={
            "trigger": trigger,
            "status": summary["status"],
            "total_files": summary["total_files"],
            "ingested_count": len(ingested),
            "skipped_count": len(skipped),
            "failed_count": len(failed),
            "dead_lettered_count": len(dead_lettered),
            "pruned_points": pruned_points,
        },
    )
    return summary


def _run_ingest_job(payload: dict) -> dict:
    """Entry point cho Kafka worker: chạy 1 ingest run từ payload của JobEvent."""
    if not main.embeddings or not main.qdrant_client:
        raise RuntimeError("Embeddings model or Qdrant client is not available.")
    files = glob.glob(main.DOCS_GLOB, recursive=True)
    if not files:
        return {"status": "no_files", "total_files": 0}
    request = IngestRequest(force=bool(payload.get("force")), prune=bool(payload.get("prune", True)))
    # Blocking: worker chỉ có 1 thread nên các run xếp hàng tuần tự thay vì chạy chồng.
    _ingest_run_lock.acquire()
    return _run_ingest(files, request, trigger=payload.get("trigger", "kafka"))


def _enqueue_ingest_job(payload: dict) -> dict:
    """Publish 1 job ingest lên Kafka + lưu job state. Ném KafkaBusError khi Kafka lỗi."""
    correlation_id = observability.get_correlation_id() or observability.set_correlation_id()
    event = ingest_worker_module.new_request_event(correlation_id=correlation_id, payload=payload)
    if main.job_store is not None:
        main.job_store.create(event.job_id, event.job_type, correlation_id, payload)
    main.kafka_bus_instance.publish_event(kafka_bus.TOPIC_REQUESTED, event)
    return {"status": "queued", "job_id": str(event.job_id), "poll": f"/ingest/jobs/{event.job_id}"}


def _run_ingest_in_background(
    files: list[str], request: IngestRequest, trigger: str = "manual", correlation_id: str | None = None
) -> None:
    # contextvars do not cross thread boundaries: re-attach the request's correlation ID.
    observability.set_correlation_id(correlation_id)
    try:
        _run_ingest(files, request, trigger)
    except Exception as e:
        logger.error(f"Background ingest run failed: {e}", exc_info=True)


def _trigger_auto_ingest(trigger: str) -> dict:
    """Kick off a background ingest right after an export lands new Markdown.

    Never raises: exports must not fail because indexing could not start.
    """
    if not main.AUTO_INGEST_AFTER_EXPORT:
        return {"status": "disabled"}
    if not main.embeddings or not main.qdrant_client:
        return {"status": "unavailable", "detail": "Embeddings model or Qdrant client is not available."}

    files = glob.glob(main.DOCS_GLOB, recursive=True)
    if not files:
        return {"status": "no_files"}

    if kafka_bus.KAFKA_ENABLED and main.kafka_bus_instance is not None:
        try:
            queued = _enqueue_ingest_job({"force": False, "prune": True, "trigger": trigger})
        except kafka_bus.KafkaBusError as e:
            logger.error(f"Failed to enqueue auto-ingest job: {e}")
            return {"status": "queue_failed", "detail": str(e)}
        return {**queued, "trigger": trigger, "total_files": len(files)}

    if not _ingest_run_lock.acquire(blocking=False):
        return {"status": "already_running", "poll": "/ingest/status"}

    threading.Thread(
        target=_run_ingest_in_background,
        args=(files, IngestRequest(), trigger, observability.get_correlation_id()),
        daemon=True,
        name="auto-ingest-worker",
    ).start()
    return {"status": "started", "trigger": trigger, "total_files": len(files), "poll": "/ingest/status"}


@router.post("/ingest")
def ingest_documents(request: IngestRequest | None = None):
    """
    Walks DOCS_GLOB and synchronizes each Markdown file with Qdrant:
    deterministic point IDs per (document, chunk), skip on unchanged content_hash,
    per-document replacement of stale chunks, pruning of deleted files, and a
    MongoDB registry with retry/dead-letter per document.
    """
    request = request or IngestRequest()
    if not main.embeddings or not main.qdrant_client:
        raise HTTPException(status_code=503, detail="Embeddings model or Qdrant client is not available.")

    files = glob.glob(main.DOCS_GLOB, recursive=True)
    if not files:
        raise HTTPException(status_code=404, detail=f"No markdown files found matching '{main.DOCS_GLOB}'.")

    # Event-driven: đẩy job vào Kafka, worker xử lý tuần tự — client không giữ kết nối.
    if kafka_bus.KAFKA_ENABLED and main.kafka_bus_instance is not None:
        try:
            queued = _enqueue_ingest_job(
                {"force": request.force, "prune": request.prune, "trigger": "manual"}
            )
        except kafka_bus.KafkaBusError as e:
            logger.error(f"Failed to enqueue ingest job: {e}")
            raise HTTPException(status_code=503, detail="Kafka is unavailable; ingest job could not be queued.")
        return JSONResponse(status_code=202, content={**queued, "total_files": len(files)})

    if not _ingest_run_lock.acquire(blocking=False):
        raise HTTPException(status_code=409, detail="An ingest run is already in progress.")

    if request.background:
        worker = threading.Thread(
            target=_run_ingest_in_background,
            args=(files, request, "manual", observability.get_correlation_id()),
            daemon=True,
            name="ingest-worker",
        )
        worker.start()
        return JSONResponse(
            status_code=202,
            content={"status": "started", "total_files": len(files), "poll": "/ingest/status"},
        )
    return _run_ingest(files, request)


@router.get("/ingest/jobs/{job_id}")
def get_ingest_job(job_id: str):
    """Trạng thái job ingest đã enqueue qua Kafka (queued/running/succeeded/...)."""
    if main.job_store is None:
        raise HTTPException(status_code=503, detail="MongoDB job store is not available.")
    try:
        parsed = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="job_id must be a UUID.")
    job = main.job_store.get(parsed)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job


@router.get("/ingest/status")
def get_ingest_status():
    with _ingest_status_lock:
        return dict(_last_ingest_status)


@router.get("/ingest/history")
def get_ingest_history(limit: int = 20):
    """Lịch sử các lần ingest (mới nhất trước), lưu bền trong MongoDB."""
    if main.ingest_history is None:
        raise HTTPException(status_code=503, detail="MongoDB ingest history is not available.")
    return {"runs": main.ingest_history.list_runs(limit=max(1, min(limit, 100)))}


def _require_document_registry() -> DocumentRegistry:
    if main.document_registry is None:
        raise HTTPException(status_code=503, detail="MongoDB document registry is not available.")
    return main.document_registry


@router.get("/ingest/documents")
def list_document_registry(status: str | None = None):
    registry = _require_document_registry()
    statuses = [status] if status else ["ingested", STATUS_FAILED, STATUS_DEAD_LETTER, "removed"]
    return {s: registry.list_by_status(s) for s in statuses}


@router.get("/ingest/dead-letter")
def list_dead_letter():
    return _require_document_registry().list_by_status(STATUS_DEAD_LETTER)


@router.post("/ingest/dead-letter/requeue")
def requeue_dead_letter(document_id: str | None = None):
    requeued = _require_document_registry().requeue(document_id)
    return {"requeued": requeued}
