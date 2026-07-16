"""Composition root của knowledge_service.

Giữ tại đây: config (env), khởi tạo client/store toàn cục, middleware,
lifecycle (startup/shutdown), health check. Endpoint theo domain nằm trong
các module routes_* (được include ở cuối file):

- routes_ingest.py            /ingest*            — đồng bộ Markdown → Qdrant
- routes_qa.py                /search /answer /sessions — hybrid retrieval + RAG
- routes_client_requests.py   /client-requests*   — gói ngữ cảnh cho agent
- routes_notebooklm.py        /ingest-excel* /ingest-spreadsheet
                              /notebook-reports /project-notebook-configs*
- schemas.py                  — Pydantic request models dùng chung

QUY ƯỚC STATE: mọi client/config toàn cục sống ở module này; các routes_*
truy cập qua `main.<attr>` tại thời điểm request. Nhờ đó test monkeypatch
trên main (main.qdrant_client, main.SERVICE_API_KEY, main._retrieve, ...)
tác động tới mọi domain. Thêm tính năng mới = thêm 1 file routes_* + include.
"""

import logging
import os
import secrets
import threading
import time

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from langchain_community.embeddings import HuggingFaceEmbeddings
from qdrant_client import QdrantClient
import openai
from pymongo import MongoClient

import ingest_worker as ingest_worker_module
import kafka_bus
import observability
import retrieval
from client_request_store import ClientRequestStore
from document_registry import DocumentRegistry
from ingest_history import IngestHistory
from job_store import MongoJobStore
from project_config_store import ProjectConfigStore
from session_store import SessionStore
from schemas import (  # re-export: test và code cũ tham chiếu qua main.<Model>
    AnswerQuery,
    ClientRequestCreate,
    IngestExcelRequest,
    IngestRequest,
    IngestSpreadsheetRequest,
    NotebookReportRequest,
    ProjectNotebookConfigUpsertRequest,
    REPORT_FORMATS,
    SearchFilters,
    SearchQuery,
)

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
    import routes_ingest

    ingest_worker = ingest_worker_module.IngestWorker(kafka_bus_instance, job_store, routes_ingest._run_ingest_job)
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


def _select_chat_client(use_online_model: int):
    """Chọn client chat dùng chung cho /answer và pipeline excel."""
    if use_online_model == 1:
        if not openai_client:
            raise HTTPException(status_code=503, detail="OPENAI_API_KEY is not configured.")
        return openai_client, OPENAI_MODEL
    if not ollama_client:
        raise HTTPException(status_code=503, detail="Ollama client is not available.")
    return ollama_client, OLLAMA_MODEL


# --- Domain routers ---
# Import ở cuối (sau khi mọi global đã định nghĩa) vì các module routes_*
# `import main` và đọc state qua main.<attr> tại thời điểm request.
import routes_ingest  # noqa: E402
import routes_qa  # noqa: E402
import routes_client_requests  # noqa: E402
import routes_notebooklm  # noqa: E402

app.include_router(routes_ingest.router)
app.include_router(routes_qa.router)
app.include_router(routes_client_requests.router)
app.include_router(routes_notebooklm.router)

# --- Compat aliases ---
# Điểm điều phối cross-domain + bề mặt monkeypatch cho test: các routes_*
# gọi main._retrieve / main._trigger_auto_ingest thay vì import chéo lẫn nhau.
_retrieve = routes_qa._retrieve
_trigger_auto_ingest = routes_ingest._trigger_auto_ingest
