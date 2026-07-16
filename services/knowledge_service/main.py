import os
import glob
import logging
import tempfile
import secrets
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException, UploadFile, File, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from langchain_community.embeddings import HuggingFaceEmbeddings
from qdrant_client import QdrantClient
from qdrant_client.http.models import (
    Distance,
    FieldCondition,
    Filter,
    FilterSelector,
    MatchAny,
    MatchText,
    MatchValue,
    PayloadSchemaType,
    PointStruct,
    TextIndexParams,
    TokenizerType,
    VectorParams,
)
import openai
from pymongo import MongoClient

import chunking
import document_identity as identity
from document_registry import (
    STATUS_DEAD_LETTER,
    STATUS_FAILED,
    DocumentRegistry,
)
import client_requests
import excel_ingest
import guardrails
import ingest_worker as ingest_worker_module
import kafka_bus
import manifest as manifest_store
import observability
import prompts
import retrieval
import vision
from client_request_store import ClientRequestStore
from ingest_history import IngestHistory
from job_store import MongoJobStore
from session_store import SessionStore, history_messages
from notebooklm_service import NotebookLMError, NotebookLMRateLimitError, NotebookLMService
from project_config_store import ProjectConfigError, ProjectConfigStore

observability.setup_logging("knowledge_service")
logger = logging.getLogger(__name__)

# --- Configuration ---
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY") or None
COLLECTION_NAME = os.getenv("COLLECTION_NAME", "project_docs")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "all-MiniLM-L6-v2")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://ollama:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
DOCS_GLOB = os.getenv("DOCS_GLOB", "/app/project_data/docs/imported/**/*.md")
CHUNK_SIZE = int(os.getenv("CHUNK_SIZE", 1000))
CHUNK_OVERLAP = int(os.getenv("CHUNK_OVERLAP", 100))
EXCEL_SOURCE_DIR = os.getenv("EXCEL_SOURCE_DIR", "/app/project_data/excel_sources")
EXCEL_OUTPUT_DIR = os.getenv("EXCEL_OUTPUT_DIR", "/app/project_data/docs/imported")
NOTEBOOKLM_OUTPUT_DIR = os.getenv("NOTEBOOKLM_OUTPUT_DIR", EXCEL_OUTPUT_DIR)
NOTEBOOKLM_AUTH_DIR = os.getenv("NOTEBOOKLM_AUTH_DIR", "/app/project_data/notebooklm_auth")
MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://mongodb:27017")
MONGODB_DB_NAME = os.getenv("MONGODB_DB_NAME", "knowledge_service")
MONGODB_COLLECTION_NAME = os.getenv("MONGODB_COLLECTION_NAME", "project_notebook_configs")
MONGODB_REGISTRY_COLLECTION = os.getenv("MONGODB_REGISTRY_COLLECTION", "document_registry")
MONGODB_SESSIONS_COLLECTION = os.getenv("MONGODB_SESSIONS_COLLECTION", "chat_sessions")
MONGODB_INGEST_HISTORY_COLLECTION = os.getenv("MONGODB_INGEST_HISTORY_COLLECTION", "ingest_runs")
MONGODB_JOBS_COLLECTION = os.getenv("MONGODB_JOBS_COLLECTION", "ingest_jobs")
MONGODB_CLIENT_REQUESTS_COLLECTION = os.getenv("MONGODB_CLIENT_REQUESTS_COLLECTION", "client_requests")
MAX_INGEST_ATTEMPTS = int(os.getenv("MAX_INGEST_ATTEMPTS", 3))
AUTO_INGEST_AFTER_EXPORT = os.getenv("AUTO_INGEST_AFTER_EXPORT", "1") == "1"
SESSION_CONTEXT_TURNS = int(os.getenv("SESSION_CONTEXT_TURNS", 5))
SESSION_MAX_TURNS = int(os.getenv("SESSION_MAX_TURNS", 20))
ENVIRONMENT = os.getenv("ENVIRONMENT", "local")
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY", "").strip()
API_KEY_HEADER = "X-API-Key"
EXEMPT_PATHS = {"/health", "/health/live", "/health/ready"}
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 120))
MAX_UPLOAD_SIZE_MB = int(os.getenv("MAX_UPLOAD_SIZE_MB", 20))
MAX_UPLOAD_BYTES = MAX_UPLOAD_SIZE_MB * 1024 * 1024
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
DEPENDENCY_CHECK_TIMEOUT = float(os.getenv("DEPENDENCY_CHECK_TIMEOUT", 5.0))

# --- Initialize Global Objects ---
try:
    embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL)
    qdrant_client = QdrantClient(host=QDRANT_HOST, port=QDRANT_PORT, api_key=QDRANT_API_KEY, https=False)
    openai_client = openai.OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None
    ollama_client = openai.OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama")
    mongo_client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=int(DEPENDENCY_CHECK_TIMEOUT * 1000))
    project_config_store = ProjectConfigStore(mongo_client[MONGODB_DB_NAME][MONGODB_COLLECTION_NAME])
    document_registry = DocumentRegistry(
        mongo_client[MONGODB_DB_NAME][MONGODB_REGISTRY_COLLECTION],
        max_attempts=MAX_INGEST_ATTEMPTS,
    )
    session_store = SessionStore(
        mongo_client[MONGODB_DB_NAME][MONGODB_SESSIONS_COLLECTION],
        max_turns=SESSION_MAX_TURNS,
    )
    ingest_history = IngestHistory(mongo_client[MONGODB_DB_NAME][MONGODB_INGEST_HISTORY_COLLECTION])
    job_store = MongoJobStore(mongo_client[MONGODB_DB_NAME][MONGODB_JOBS_COLLECTION])
    client_request_store = ClientRequestStore(mongo_client[MONGODB_DB_NAME][MONGODB_CLIENT_REQUESTS_COLLECTION])
    reranker = retrieval.Reranker() if retrieval.RERANK_ENABLED else None
except Exception as e:
    logger.error(f"Failed to initialize models or clients on startup: {e}", exc_info=True)
    embeddings = None
    qdrant_client = None
    openai_client = None
    ollama_client = None
    mongo_client = None
    project_config_store = None
    document_registry = None
    session_store = None
    ingest_history = None
    job_store = None
    client_request_store = None
    reranker = None

kafka_bus_instance = kafka_bus.KafkaBus() if kafka_bus.KAFKA_ENABLED else None
ingest_worker: ingest_worker_module.IngestWorker | None = None

app = FastAPI(title="Knowledge Curator Service")

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=[API_KEY_HEADER, "Content-Type"],
    )

@app.on_event("startup")
def enforce_service_api_key():
    if not SERVICE_API_KEY:
        raise RuntimeError(
            "SERVICE_API_KEY must be set to a non-empty value. Refusing to start knowledge_service."
        )


@app.on_event("startup")
def start_kafka_ingest_worker():
    global ingest_worker
    if not kafka_bus.KAFKA_ENABLED:
        return
    if job_store is None:
        logger.error("Kafka is enabled but the MongoDB job store is unavailable; ingest worker not started.")
        return
    ingest_worker = ingest_worker_module.IngestWorker(kafka_bus_instance, job_store, _run_ingest_job)
    ingest_worker.start()


@app.on_event("shutdown")
def stop_kafka_ingest_worker():
    if ingest_worker is not None:
        ingest_worker.stop()
    if kafka_bus_instance is not None:
        kafka_bus_instance.close()


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path in EXEMPT_PATHS:
        return await call_next(request)
    if not SERVICE_API_KEY:
        logger.error("SERVICE_API_KEY is not configured for knowledge_service.")
        return JSONResponse(status_code=503, content={"detail": "SERVICE_API_KEY is not configured."})

    provided_key = request.headers.get(API_KEY_HEADER, "")
    if not secrets.compare_digest(provided_key, SERVICE_API_KEY):
        return JSONResponse(status_code=401, content={"detail": "Invalid or missing API key."})
    return await call_next(request)


_rate_buckets: dict[str, tuple[float, int]] = {}
_rate_lock = threading.Lock()


@app.middleware("http")
async def limit_request_rate(request: Request, call_next):
    if request.url.path in EXEMPT_PATHS or RATE_LIMIT_PER_MINUTE <= 0:
        return await call_next(request)

    client_ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _rate_lock:
        window_start, count = _rate_buckets.get(client_ip, (now, 0))
        if now - window_start >= 60.0:
            window_start, count = now, 0
        count += 1
        _rate_buckets[client_ip] = (window_start, count)
    if count > RATE_LIMIT_PER_MINUTE:
        return JSONResponse(
            status_code=429,
            content={"detail": "Rate limit exceeded. Please retry later."},
            headers={"Retry-After": str(int(60 - (now - window_start)) + 1)},
        )
    return await call_next(request)


@app.middleware("http")
async def limit_request_body_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > MAX_UPLOAD_BYTES:
        return JSONResponse(
            status_code=413,
            content={"detail": f"Request body exceeds the {MAX_UPLOAD_SIZE_MB} MB limit."},
        )
    return await call_next(request)


# Registered last so it wraps every other middleware: the correlation ID is set
# before auth/rate-limit code runs and therefore appears on all their log lines.
@app.middleware("http")
async def correlate_and_log_request(request: Request, call_next):
    correlation_id = observability.set_correlation_id(
        request.headers.get(observability.REQUEST_ID_HEADER)
    )
    started = time.perf_counter()
    response = await call_next(request)
    response.headers[observability.REQUEST_ID_HEADER] = correlation_id
    if request.url.path not in EXEMPT_PATHS:  # health probes would flood the log
        logger.info(
            "http_request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": observability.duration_ms(started),
            },
        )
    return response


class SearchFilters(BaseModel):
    project: str | None = None
    environment: str | None = None
    document_type: str | None = None
    version: int | None = None


class SearchQuery(BaseModel):
    query: str
    limit: int = 3
    filters: SearchFilters | None = None


class AnswerQuery(BaseModel):
    question: str
    limit: int = 3
    use_online_model: int = 0  # 0 = Ollama (local), 1 = OpenAI gpt-4o-mini (online)
    filters: SearchFilters | None = None
    session_id: str | None = None  # bật hội thoại nhiều lượt khi client gửi kèm
    prompt_version: str | None = None  # mặc định theo PROMPT_VERSION (env)


class ClientRequestCreate(BaseModel):
    title: str
    description: str
    request_type: str = "feature"  # feature | bug
    project: str | None = None  # lọc đặc tả theo dự án nếu chỉ định
    requester: str | None = None
    limit: int = 8  # số trích đoạn đặc tả tối đa trong gói ngữ cảnh


class IngestExcelRequest(BaseModel):
    use_online_model: int = 0  # 0 = Ollama (local), 1 = OpenAI gpt-4o-mini (online) cho bước refine
    force: bool = False


class IngestSpreadsheetRequest(BaseModel):
    project_name: str
    notebook_env: str
    spreadsheet_id: str
    output_name: str = "spreadsheet.md"

    @field_validator("project_name", "notebook_env")
    @classmethod
    def validate_scope_name(cls, value: str) -> str:
        return _validate_storage_name(value, "scope")

    @field_validator("output_name")
    @classmethod
    def validate_output_name(cls, value: str) -> str:
        _validate_output_name(value)
        return value


class ProjectNotebookConfigUpsertRequest(BaseModel):
    project_name: str
    notebook_env: str
    notebook_id: str
    notebooklm_auth_name: str

    @field_validator("project_name", "notebook_env")
    @classmethod
    def validate_scope_name(cls, value: str) -> str:
        return _validate_storage_name(value, "scope")

    @field_validator("notebook_id")
    @classmethod
    def validate_notebook_id(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("notebook_id must not be empty.")
        return value

    @field_validator("notebooklm_auth_name")
    @classmethod
    def validate_auth_name(cls, value: str) -> str:
        return _validate_auth_name(value)


def _ensure_collection(vector_size: int):
    existing = [c.name for c in qdrant_client.get_collections().collections]
    if COLLECTION_NAME not in existing:
        qdrant_client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config=VectorParams(size=vector_size, distance=Distance.COSINE),
        )


def _validate_storage_name(value: str, label: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{label} must not be empty.")
    if any(char in value for char in ("/", "\\", "..")):
        raise ValueError(f"{label} must not contain path separators or '..'.")
    return value


def _validate_output_name(value: str) -> None:
    if "/" in value or "\\" in value or not value.endswith(".md"):
        raise ValueError("output_name must be a plain .md filename.")


def _validate_auth_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("notebooklm_auth_name must not be empty.")
    if any(char in value for char in ("/", "\\", "..")):
        raise ValueError("notebooklm_auth_name must not contain path separators or '..'.")
    if not value.endswith(".json"):
        raise ValueError("notebooklm_auth_name must end with .json.")
    return value


def _require_project_config_store() -> ProjectConfigStore:
    if project_config_store is None:
        raise HTTPException(status_code=503, detail="MongoDB project config store is not available.")
    return project_config_store


def _load_notebook_auth_json(auth_name: str) -> str:
    auth_name = _validate_auth_name(auth_name)
    auth_path = Path(NOTEBOOKLM_AUTH_DIR) / auth_name
    if not auth_path.is_file():
        raise HTTPException(
            status_code=404,
            detail=f"NotebookLM auth file '{auth_name}' was not found in auth directory.",
        )
    return auth_path.read_text(encoding="utf-8")


def _project_output_dir(project_name: str) -> str:
    return str(Path(NOTEBOOKLM_OUTPUT_DIR) / project_name)


@app.get("/health")
@app.get("/health/live")
def health_live():
    """Liveness: the process is up and can serve HTTP."""
    return {"status": "ok", "service": "knowledge_service"}


@app.get("/health/ready")
def health_ready():
    """Readiness: every hard dependency answers, at least one AI provider is usable."""
    checks: dict[str, str] = {}

    if qdrant_client is None:
        checks["qdrant"] = "not_initialized"
    else:
        try:
            qdrant_client.get_collections()
            checks["qdrant"] = "ok"
        except Exception as e:
            checks["qdrant"] = f"error: {e}"

    if mongo_client is None:
        checks["mongodb"] = "not_initialized"
    else:
        try:
            mongo_client.admin.command("ping")
            checks["mongodb"] = "ok"
        except Exception as e:
            checks["mongodb"] = f"error: {e}"

    checks["embedding_model"] = "ok" if embeddings else "not_initialized"

    if ollama_client is None:
        checks["ollama"] = "not_initialized"
    else:
        try:
            response = httpx.get(f"{OLLAMA_BASE_URL.rstrip('/')}/models", timeout=DEPENDENCY_CHECK_TIMEOUT)
            checks["ollama"] = "ok" if response.status_code < 500 else f"http_{response.status_code}"
        except httpx.HTTPError as e:
            checks["ollama"] = f"unreachable: {e}"

    checks["openai"] = "configured" if openai_client else "not_configured"

    if kafka_bus.KAFKA_ENABLED:
        checks["kafka"] = (
            "ok" if kafka_bus_instance is not None and kafka_bus_instance.ping() else "unreachable"
        )

    ai_provider_ok = checks["ollama"] == "ok" or checks["openai"] == "configured"
    kafka_ok = not kafka_bus.KAFKA_ENABLED or checks.get("kafka") == "ok"
    ready = (
        checks["qdrant"] == "ok"
        and checks["mongodb"] == "ok"
        and checks["embedding_model"] == "ok"
        and ai_provider_ok
        and kafka_ok
    )
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "service": "knowledge_service", "checks": checks},
    )


@app.get("/")
def read_root():
    return {"message": "Knowledge Curator Service is running."}


class IngestRequest(BaseModel):
    force: bool = False  # re-embed even when content_hash is unchanged (also retries dead-lettered docs)
    prune: bool = True  # delete vectors whose source file no longer exists
    background: bool = False  # run in a worker thread; poll /ingest/status for the result


_ingest_status_lock = threading.Lock()
_last_ingest_status: dict = {"status": "never_run"}


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
    return COLLECTION_NAME in [c.name for c in qdrant_client.get_collections().collections]


def _ensure_payload_indexes():
    keyword_fields = ("document_id", "source", "content_hash", "project", "environment", "document_type")
    for field in keyword_fields:
        try:
            qdrant_client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field,
                field_schema=PayloadSchemaType.KEYWORD,
            )
        except Exception:
            pass  # index already exists
    try:
        qdrant_client.create_payload_index(
            collection_name=COLLECTION_NAME,
            field_name="version",
            field_schema=PayloadSchemaType.INTEGER,
        )
    except Exception:
        pass
    try:
        # Full-text index over chunk text: powers the keyword half of hybrid search.
        qdrant_client.create_payload_index(
            collection_name=COLLECTION_NAME,
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
    docs_root = DOCS_GLOB.split("*", 1)[0].rstrip("/")
    try:
        parts = Path(os.path.relpath(file_path, docs_root)).parts
    except ValueError:
        parts = ()
    project = parts[0] if len(parts) > 1 else "default"
    return {
        "project": project,
        "environment": ENVIRONMENT,
        "document_type": Path(file_path).suffix.lstrip(".").lower() or "unknown",
    }


def _build_search_filter(filters: SearchFilters | None) -> Filter | None:
    if filters is None:
        return None
    conditions = [
        FieldCondition(key=field, match=MatchValue(value=value))
        for field, value in filters.model_dump().items()
        if value is not None
    ]
    return Filter(must=conditions) if conditions else None


def _document_filter(doc_id: str) -> Filter:
    return Filter(must=[FieldCondition(key="document_id", match=MatchValue(value=doc_id))])


def _existing_document_state(doc_id: str) -> tuple[str | None, int]:
    """Return (content_hash, version) of the currently indexed document, if any."""
    points, _ = qdrant_client.scroll(
        collection_name=COLLECTION_NAME,
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
    deleted = qdrant_client.count(collection_name=COLLECTION_NAME, count_filter=points_filter, exact=True).count
    if deleted:
        qdrant_client.delete(
            collection_name=COLLECTION_NAME,
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

    chunks = chunking.split_markdown(text, chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    if not chunks:
        deleted = _delete_by_filter(_document_filter(doc_id)) if collection_ready else 0
        return {
            "file": file_path,
            "document_id": doc_id,
            "action": "emptied",
            "deleted_points": deleted,
        }, collection_ready

    vectors = embeddings.embed_documents([chunk.text for chunk in chunks])
    if not collection_ready:
        _ensure_collection(len(vectors[0]))
        collection_ready = True
    _ensure_payload_indexes()

    version = old_version + 1
    ingested_at = _utc_now_iso()
    metadata = _document_metadata(file_path)
    qdrant_client.upsert(
        collection_name=COLLECTION_NAME,
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


_ingest_run_lock = threading.Lock()


def _record_ingest_history(summary: dict, trigger: str) -> None:
    if ingest_history is None:
        return
    try:
        ingest_history.record(summary, trigger=trigger)
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
                and document_registry is not None
                and document_registry.is_dead_lettered(doc_id, file_hash)
            ):
                dead_lettered.append({"file": file_path, "document_id": doc_id})
                continue

            try:
                result, collection_ready = _sync_document(file_path, request.force, collection_ready)
            except Exception as e:
                logger.error(f"Failed to ingest '{file_path}': {e}", exc_info=True)
                failure = {"file": file_path, "document_id": doc_id, "error": str(e)}
                if document_registry is not None:
                    failure.update(
                        document_registry.record_failure(
                            doc_id, source=file_path, content_hash=file_hash, error=str(e)
                        )
                    )
                failed.append(failure)
                continue

            (skipped if result["action"] == "skipped" else ingested).append(result)
            if document_registry is not None and result["action"] != "skipped":
                document_registry.record_ingested(
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
            if document_registry is not None:
                document_registry.mark_removed_except(current_doc_ids)
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
    if not embeddings or not qdrant_client:
        raise RuntimeError("Embeddings model or Qdrant client is not available.")
    files = glob.glob(DOCS_GLOB, recursive=True)
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
    if job_store is not None:
        job_store.create(event.job_id, event.job_type, correlation_id, payload)
    kafka_bus_instance.publish_event(kafka_bus.TOPIC_REQUESTED, event)
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
    if not AUTO_INGEST_AFTER_EXPORT:
        return {"status": "disabled"}
    if not embeddings or not qdrant_client:
        return {"status": "unavailable", "detail": "Embeddings model or Qdrant client is not available."}

    files = glob.glob(DOCS_GLOB, recursive=True)
    if not files:
        return {"status": "no_files"}

    if kafka_bus.KAFKA_ENABLED and kafka_bus_instance is not None:
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


@app.post("/ingest")
def ingest_documents(request: IngestRequest | None = None):
    """
    Walks DOCS_GLOB and synchronizes each Markdown file with Qdrant:
    deterministic point IDs per (document, chunk), skip on unchanged content_hash,
    per-document replacement of stale chunks, pruning of deleted files, and a
    MongoDB registry with retry/dead-letter per document.
    """
    request = request or IngestRequest()
    if not embeddings or not qdrant_client:
        raise HTTPException(status_code=503, detail="Embeddings model or Qdrant client is not available.")

    files = glob.glob(DOCS_GLOB, recursive=True)
    if not files:
        raise HTTPException(status_code=404, detail=f"No markdown files found matching '{DOCS_GLOB}'.")

    # Event-driven: đẩy job vào Kafka, worker xử lý tuần tự — client không giữ kết nối.
    if kafka_bus.KAFKA_ENABLED and kafka_bus_instance is not None:
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


@app.get("/ingest/jobs/{job_id}")
def get_ingest_job(job_id: str):
    """Trạng thái job ingest đã enqueue qua Kafka (queued/running/succeeded/...)."""
    if job_store is None:
        raise HTTPException(status_code=503, detail="MongoDB job store is not available.")
    try:
        parsed = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=422, detail="job_id must be a UUID.")
    job = job_store.get(parsed)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return job


@app.get("/ingest/status")
def get_ingest_status():
    with _ingest_status_lock:
        return dict(_last_ingest_status)


@app.get("/ingest/history")
def get_ingest_history(limit: int = 20):
    """Lịch sử các lần ingest (mới nhất trước), lưu bền trong MongoDB."""
    if ingest_history is None:
        raise HTTPException(status_code=503, detail="MongoDB ingest history is not available.")
    return {"runs": ingest_history.list_runs(limit=max(1, min(limit, 100)))}


def _require_document_registry() -> DocumentRegistry:
    if document_registry is None:
        raise HTTPException(status_code=503, detail="MongoDB document registry is not available.")
    return document_registry


@app.get("/ingest/documents")
def list_document_registry(status: str | None = None):
    registry = _require_document_registry()
    statuses = [status] if status else ["ingested", STATUS_FAILED, STATUS_DEAD_LETTER, "removed"]
    return {s: registry.list_by_status(s) for s in statuses}


@app.get("/ingest/dead-letter")
def list_dead_letter():
    return _require_document_registry().list_by_status(STATUS_DEAD_LETTER)


@app.post("/ingest/dead-letter/requeue")
def requeue_dead_letter(document_id: str | None = None):
    requeued = _require_document_registry().requeue(document_id)
    return {"requeued": requeued}


def _candidate_from_payload(point_id, payload: dict, vector_score: float | None = None) -> dict:
    return {
        "id": str(point_id),
        "text": payload.get("text"),
        "source": payload.get("source"),
        "heading": payload.get("heading", ""),
        "start_line": payload.get("start_line"),
        "end_line": payload.get("end_line"),
        "vector_score": vector_score,
        "keyword_score": None,
    }


def _dense_candidates(query: str, pool: int, query_filter: Filter | None) -> list[dict]:
    query_vector = embeddings.embed_query(query)
    results = qdrant_client.query_points(
        collection_name=COLLECTION_NAME,
        query=query_vector,
        limit=pool,
        query_filter=query_filter,
    )
    return [_candidate_from_payload(r.id, r.payload or {}, vector_score=r.score) for r in results.points]


def _keyword_candidates(query: str, pool: int, query_filter: Filter | None) -> list[dict]:
    """Full-text candidates via the Qdrant text index, scored locally with BM25."""
    terms = retrieval.query_terms(query)
    if not terms:
        return []
    text_filter = Filter(should=[FieldCondition(key="text", match=MatchText(text=term)) for term in terms])
    combined = Filter(must=[query_filter, text_filter]) if query_filter else text_filter
    try:
        points, _ = qdrant_client.scroll(
            collection_name=COLLECTION_NAME,
            scroll_filter=combined,
            limit=pool,
            with_payload=True,
            with_vectors=False,
        )
    except Exception as e:
        logger.warning(f"Keyword search unavailable, falling back to dense-only: {e}")
        return []

    candidates = [_candidate_from_payload(p.id, p.payload or {}) for p in points]
    scores = retrieval.bm25_scores(terms, [c["text"] or "" for c in candidates])
    for candidate, score in zip(candidates, scores):
        candidate["keyword_score"] = score
    candidates = [c for c in candidates if (c["keyword_score"] or 0) > 0]
    candidates.sort(key=lambda c: c["keyword_score"], reverse=True)
    return candidates[:pool]


def _retrieve(query: str, limit: int, filters: SearchFilters | None) -> tuple[list[dict], dict]:
    """Hybrid retrieval pipeline. Returns (matches, retrieval_info)."""
    if not embeddings or not qdrant_client:
        raise HTTPException(status_code=503, detail="Embeddings model or Qdrant client is not available.")

    query_filter = _build_search_filter(filters)
    pool = max(limit * retrieval.CANDIDATE_POOL_MULTIPLIER, 20)

    started = time.perf_counter()
    dense = _dense_candidates(query, pool, query_filter)
    dense_ms = observability.duration_ms(started)

    keyword_started = time.perf_counter()
    keyword = _keyword_candidates(query, pool, query_filter) if retrieval.HYBRID_SEARCH_ENABLED else []
    keyword_ms = observability.duration_ms(keyword_started)

    # Rerank looks at a wider pool than the final limit so it can rescue candidates.
    rerank_pool = limit * 2 if reranker else limit
    fused = retrieval.fuse_candidates(dense, keyword, limit=max(rerank_pool, limit))

    rerank_started = time.perf_counter()
    reranked = bool(reranker) and reranker.rerank(query, fused)
    rerank_ms = observability.duration_ms(rerank_started)
    kept = retrieval.apply_threshold(fused, use_rerank_floor=reranked)[:limit]

    timings_ms = {
        "dense_search": dense_ms,
        "keyword_search": keyword_ms,
        "rerank": rerank_ms,
        "total": observability.duration_ms(started),
    }
    info = {
        "mode": "hybrid" if keyword else "dense",
        "reranked": reranked,
        "min_score": retrieval.MIN_RERANK_SCORE if reranked else retrieval.MIN_SCORE_THRESHOLD,
        "candidates": {"dense": len(dense), "keyword": len(keyword)},
        "dropped_below_threshold": len(fused) - len(retrieval.apply_threshold(fused, use_rerank_floor=reranked)),
        "timings_ms": timings_ms,
    }
    logger.info(
        "qdrant_retrieval",
        extra={
            "mode": info["mode"],
            "limit": limit,
            "kept": len(kept),
            "dense_candidates": len(dense),
            "keyword_candidates": len(keyword),
            "reranked": reranked,
            **{f"{name}_ms": value for name, value in timings_ms.items()},
        },
    )
    return kept, info


@app.post("/search")
def search_documents(search_query: SearchQuery) -> list:
    matches, _ = _retrieve(search_query.query, search_query.limit, search_query.filters)
    return [
        {
            "text": m["text"],
            "source": m["source"],
            "heading": m["heading"],
            "start_line": m["start_line"],
            "end_line": m["end_line"],
            "score": retrieval.relevance_score(m),
            "vector_score": m.get("vector_score"),
            "keyword_score": m.get("keyword_score"),
            "rerank_score": m.get("rerank_score"),
        }
        for m in matches
    ]


@app.post("/answer")
def get_answer(answer_query: AnswerQuery):
    use_online = answer_query.use_online_model == 1
    client, model = _select_chat_client(answer_query.use_online_model)

    prompt_version = answer_query.prompt_version or prompts.DEFAULT_PROMPT_VERSION
    if prompt_version not in prompts.available_versions():
        raise HTTPException(
            status_code=422,
            detail=f"Unknown prompt_version '{prompt_version}'. Available: {prompts.available_versions()}",
        )

    matches, retrieval_info = _retrieve(answer_query.question, answer_query.limit, answer_query.filters)
    if not matches:
        raise HTTPException(
            status_code=404,
            detail=(
                "No documents passed the relevance threshold for this question; "
                "refusing to answer from unrelated context."
            ),
        )

    citations = []
    context_blocks = []
    sanitized_any = False
    for index, m in enumerate(matches, start=1):
        clean_text, modified = guardrails.sanitize_chunk(m["text"] or "")
        sanitized_any = sanitized_any or modified
        lines = f"{m['start_line']}-{m['end_line']}" if m.get("start_line") else "?"
        context_blocks.append(
            guardrails.render_context_block(index, m["source"], m["heading"], lines, clean_text)
        )
        citations.append(
            {
                "context_id": f"context-{index}",
                "source": m["source"],
                "heading": m["heading"],
                "start_line": m.get("start_line"),
                "end_line": m.get("end_line"),
                "score": retrieval.relevance_score(m),
            }
        )

    messages = prompts.build_messages(
        prompt_version, context="\n\n".join(context_blocks), question=answer_query.question
    )
    if answer_query.session_id and session_store is not None:
        # Insert prior turns between the system message (if any) and the final user message.
        turns = session_store.get_turns(answer_query.session_id, SESSION_CONTEXT_TURNS)
        if turns:
            messages = messages[:-1] + history_messages(turns) + messages[-1:]

    llm_started = time.perf_counter()
    try:
        completion = client.chat.completions.create(model=model, messages=messages)
    except Exception as e:
        logger.error(f"Chat completion failed (model={model}, online={use_online}): {e}", exc_info=True)
        raise HTTPException(status_code=502, detail=f"Failed to get response from model '{model}'.")
    observability.log_llm_usage(
        logger, "llm_completion", model=model, started=llm_started, completion=completion, purpose="answer"
    )

    answer_text = completion.choices[0].message.content
    if answer_query.session_id and session_store is not None:
        try:
            session_store.append_turn(answer_query.session_id, answer_query.question, answer_text)
        except Exception as e:
            logger.error(f"Failed to persist session turn: {e}", exc_info=True)

    return {
        "answer": answer_text,
        "sources": [m["source"] for m in matches],
        "citations": citations,
        "model_used": model,
        "prompt_version": prompt_version,
        "session_id": answer_query.session_id,
        "retrieval": retrieval_info,
        "context_sanitized": sanitized_any,
    }


@app.get("/sessions/{session_id}")
def get_session(session_id: str):
    if session_store is None:
        raise HTTPException(status_code=503, detail="MongoDB session store is not available.")
    session = session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return session


@app.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    if session_store is None:
        raise HTTPException(status_code=503, detail="MongoDB session store is not available.")
    if not session_store.delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return {"deleted": True, "session_id": session_id}


# --- Yêu cầu từ khách hàng (client requests) ---
# Tiếp nhận yêu cầu thêm tính năng / sửa lỗi, truy xuất các đặc tả hiện có
# liên quan và đóng gói thành ngữ cảnh có trích dẫn cho agent PM/Coder/Tester.


def _require_client_request_store() -> ClientRequestStore:
    if client_request_store is None:
        raise HTTPException(status_code=503, detail="MongoDB client request store is not available.")
    return client_request_store


def _get_client_request_or_404(request_id: str) -> dict:
    record = _require_client_request_store().get(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Client request '{request_id}' not found.")
    return record


def _analyze_client_request(record: dict, limit: int) -> dict:
    query_text = f"{record['title']}\n{record['description']}".strip()
    filters = SearchFilters(project=record["project"]) if record.get("project") else None
    matches, retrieval_info = _retrieve(query_text, limit, filters)
    excerpts = [
        {
            "text": m["text"],
            "source": m["source"],
            "heading": m["heading"],
            "start_line": m["start_line"],
            "end_line": m["end_line"],
            "score": retrieval.relevance_score(m),
        }
        for m in matches
    ]
    return client_requests.build_context_package(query_text, excerpts, retrieval_info)


@app.post("/client-requests", status_code=201)
def create_client_request(payload: ClientRequestCreate):
    store = _require_client_request_store()
    if payload.request_type not in client_requests.REQUEST_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"request_type must be one of {list(client_requests.REQUEST_TYPES)}.",
        )
    if not payload.title.strip() or not payload.description.strip():
        raise HTTPException(status_code=422, detail="title and description must be non-empty.")

    record = store.create(
        title=payload.title.strip(),
        description=payload.description.strip(),
        request_type=payload.request_type,
        project=payload.project,
        requester=payload.requester,
    )
    package = _analyze_client_request(record, payload.limit)
    store.save_context(record["request_id"], package)
    record["context"] = package
    logger.info(
        "client_request_created",
        extra={
            "request_id": record["request_id"],
            "request_type": record["request_type"],
            "has_related_specs": package["has_related_specs"],
            "excerpts": len(package["excerpts"]),
        },
    )
    return record


@app.get("/client-requests")
def list_client_requests(limit: int = 50):
    return _require_client_request_store().list(limit=max(1, min(limit, 200)))


@app.get("/client-requests/{request_id}")
def get_client_request(request_id: str):
    return _get_client_request_or_404(request_id)


@app.get("/client-requests/{request_id}/context")
def get_client_request_context(request_id: str, role: str = "coder"):
    """Gói ngữ cảnh + markdown sẵn dùng cho agent theo vai trò (pm/coder/tester)."""
    if role not in client_requests.AGENT_ROLES:
        raise HTTPException(
            status_code=422, detail=f"role must be one of {list(client_requests.AGENT_ROLES)}."
        )
    record = _get_client_request_or_404(request_id)
    package = record.get("context")
    if not package:
        raise HTTPException(
            status_code=409,
            detail=f"Client request '{request_id}' has no context yet; call POST /client-requests/{request_id}/reanalyze.",
        )
    return {
        "request_id": request_id,
        "role": role,
        "context": package,
        "markdown": client_requests.render_context_markdown(record, package, role),
    }


@app.post("/client-requests/{request_id}/reanalyze")
def reanalyze_client_request(request_id: str, limit: int = 8):
    """Chạy lại truy xuất — dùng sau khi ingest thêm/cập nhật đặc tả."""
    record = _get_client_request_or_404(request_id)
    package = _analyze_client_request(record, max(1, min(limit, 20)))
    _require_client_request_store().save_context(request_id, package)
    record["context"] = package
    return record


def _select_chat_client(use_online_model: int):
    if use_online_model == 1:
        if not openai_client:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")
        return openai_client, OPENAI_MODEL
    if not ollama_client:
        raise HTTPException(status_code=503, detail="Ollama client is not available.")
    return ollama_client, OLLAMA_MODEL


def _check_vision_available():
    if vision.VISION_PROVIDER == "anthropic" and not vision.anthropic_vision_client:
        raise HTTPException(
            status_code=503,
            detail="ANTHROPIC_API_KEY is not configured (required for VISION_PROVIDER=anthropic).",
        )
    if vision.VISION_PROVIDER == "openai" and not vision.openai_vision_client:
        raise HTTPException(
            status_code=503,
            detail="OPENAI_API_KEY is not configured (required for VISION_PROVIDER=openai).",
        )


@app.post("/ingest-excel")
def ingest_excel(request: IngestExcelRequest):
    """
    Quét EXCEL_SOURCE_DIR, convert từng file .xlsx chưa xử lý (hoặc đã đổi nội dung) thành
    Markdown trong EXCEL_OUTPUT_DIR, dùng vision LLM để caption ảnh nhúng và text LLM để làm sạch
    format cuối cùng.
    """
    _check_vision_available()
    client, model = _select_chat_client(request.use_online_model)

    files = glob.glob(os.path.join(EXCEL_SOURCE_DIR, "*.xlsx"))
    if not files:
        raise HTTPException(status_code=404, detail=f"No .xlsx files found in '{EXCEL_SOURCE_DIR}'.")

    manifest = manifest_store.load_manifest(EXCEL_OUTPUT_DIR)
    processed, skipped, failed = [], [], []

    for path in files:
        name = os.path.basename(path)
        with open(path, "rb") as f:
            content = f.read()
        content_hash = manifest_store.compute_hash(content)

        if not request.force and manifest_store.is_unchanged(manifest, name, content_hash):
            skipped.append(name)
            continue

        try:
            result = excel_ingest.process_excel_file(path, EXCEL_OUTPUT_DIR, client, model)
            manifest_store.record_success(manifest, name, content_hash, result["output_md"], result["image_count"])
            manifest_store.save_manifest(EXCEL_OUTPUT_DIR, manifest)
            processed.append({"file": name, **result})
        except Exception as e:
            logger.error(f"Failed to process '{name}': {e}", exc_info=True)
            failed.append({"file": name, "error": str(e)})

    auto_ingest = _trigger_auto_ingest("excel_export") if processed else {"status": "skipped"}
    return {"processed": processed, "skipped": skipped, "failed": failed, "auto_ingest": auto_ingest}


@app.post("/ingest-excel/upload")
async def ingest_excel_upload(use_online_model: int = 0, file: UploadFile = File(...)):
    """Upload 1 file .xlsx ad-hoc và xử lý ngay (không qua manifest skip)."""
    content = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Uploaded file exceeds the {MAX_UPLOAD_SIZE_MB} MB limit.",
        )

    _check_vision_available()
    client, model = _select_chat_client(use_online_model)
    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
        tmp.write(content)
        tmp_path = tmp.name

    try:
        result = excel_ingest.process_excel_file(tmp_path, EXCEL_OUTPUT_DIR, client, model)
    except Exception as e:
        logger.error(f"Failed to process uploaded file '{file.filename}': {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to process uploaded file: {e}")
    finally:
        os.remove(tmp_path)

    manifest = manifest_store.load_manifest(EXCEL_OUTPUT_DIR)
    content_hash = manifest_store.compute_hash(content)
    manifest_store.record_success(manifest, file.filename, content_hash, result["output_md"], result["image_count"])
    manifest_store.save_manifest(EXCEL_OUTPUT_DIR, manifest)

    return {"file": file.filename, **result, "auto_ingest": _trigger_auto_ingest("excel_upload")}


@app.post("/ingest-spreadsheet")
def ingest_spreadsheet(request: IngestSpreadsheetRequest):
    """Resolve project NotebookLM config from MongoDB and export Markdown."""
    store = _require_project_config_store()
    try:
        config = store.get_config(request.project_name, request.notebook_env)
    except ProjectConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    auth_json = _load_notebook_auth_json(config.notebooklm_auth_name)
    output_dir = _project_output_dir(request.project_name)
    service = NotebookLMService(
        notebook_id=config.notebook_id,
        output_dir=output_dir,
        auth_json=auth_json,
    )
    try:
        result = service.process_spreadsheet(request.spreadsheet_id, request.output_name)
    except NotebookLMRateLimitError as exc:
        logger.warning("NotebookLM rate limit; job can be resumed without creating a duplicate: %s", exc)
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except NotebookLMError as exc:
        logger.error("NotebookLM spreadsheet ingestion failed: %s", exc)
        status_code = 503 if "not configured" in str(exc) else 502
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc

    manifest = manifest_store.load_manifest(output_dir)
    manifest_store.record_success(
        manifest,
        request.spreadsheet_id,
        manifest_store.compute_hash(request.spreadsheet_id.encode("utf-8")),
        result.output_md,
        0,
        project_name=request.project_name,
        notebook_env=request.notebook_env,
        notebook_id=service.notebook_id,
        notebooklm_auth_name=config.notebooklm_auth_name,
        source_id=result.source_id,
        artifact_id=result.artifact_id,
        spreadsheet_id=request.spreadsheet_id,
    )
    manifest_store.save_manifest(output_dir, manifest)

    return {
        "project_name": request.project_name,
        "notebook_env": request.notebook_env,
        "spreadsheet_id": request.spreadsheet_id,
        "notebook_id": service.notebook_id,
        "source_id": result.source_id,
        "artifact_id": result.artifact_id,
        "output_md": result.output_md,
        "auto_ingest": _trigger_auto_ingest("notebooklm_export"),
    }


@app.post("/project-notebook-configs")
def upsert_project_notebook_config(request: ProjectNotebookConfigUpsertRequest):
    store = _require_project_config_store()
    _load_notebook_auth_json(request.notebooklm_auth_name)
    config = store.upsert_config(
        request.project_name,
        request.notebook_env,
        request.notebook_id,
        request.notebooklm_auth_name,
    )
    return config.__dict__


@app.get("/project-notebook-configs")
def list_all_project_notebook_configs():
    store = _require_project_config_store()
    grouped: dict[str, list[dict]] = {}
    for config in store.list_all_configs():
        grouped.setdefault(config.project_name, []).append(config.__dict__)
    return [
        {"project_name": project_name, "config_count": len(configs), "configs": configs}
        for project_name, configs in grouped.items()
    ]


@app.get("/project-notebook-configs/{project_name}")
def list_project_notebook_configs(project_name: str):
    store = _require_project_config_store()
    try:
        project_name = _validate_storage_name(project_name, "project_name")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return [config.__dict__ for config in store.list_configs(project_name)]


@app.get("/project-notebook-configs/{project_name}/{notebook_env}")
def get_project_notebook_config(project_name: str, notebook_env: str):
    store = _require_project_config_store()
    try:
        project_name = _validate_storage_name(project_name, "project_name")
        notebook_env = _validate_storage_name(notebook_env, "notebook_env")
        config = store.get_config(project_name, notebook_env)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ProjectConfigError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return config.__dict__


@app.put("/project-notebook-configs/{project_name}/{notebook_env}")
def update_project_notebook_config(
    project_name: str,
    notebook_env: str,
    request: ProjectNotebookConfigUpsertRequest,
):
    store = _require_project_config_store()
    try:
        project_name = _validate_storage_name(project_name, "project_name")
        notebook_env = _validate_storage_name(notebook_env, "notebook_env")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if request.project_name != project_name or request.notebook_env != notebook_env:
        raise HTTPException(
            status_code=422,
            detail="Path project_name/notebook_env must match request body.",
        )
    _load_notebook_auth_json(request.notebooklm_auth_name)
    config = store.upsert_config(
        project_name,
        notebook_env,
        request.notebook_id,
        request.notebooklm_auth_name,
    )
    return config.__dict__


@app.delete("/project-notebook-configs/{project_name}/{notebook_env}")
def delete_project_notebook_config(project_name: str, notebook_env: str):
    store = _require_project_config_store()
    try:
        project_name = _validate_storage_name(project_name, "project_name")
        notebook_env = _validate_storage_name(notebook_env, "notebook_env")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    deleted = store.delete_config(project_name, notebook_env)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Config not found for project_name='{project_name}' and notebook_env='{notebook_env}'.",
        )
    return {"deleted": True, "project_name": project_name, "notebook_env": notebook_env}
