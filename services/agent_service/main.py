import os
import logging
import secrets
import threading
import time

import httpx
import git
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

import observability

observability.setup_logging("agent_service")
logger = logging.getLogger(__name__)

# --- Configuration ---
PROJECT_PATH = os.getenv("PROJECT_PATH", "/app/project_data")
KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://knowledge_service:8000")
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY", "").strip()
API_KEY_HEADER = "X-API-Key"
EXEMPT_PATHS = {"/health", "/health/live", "/health/ready"}
RATE_LIMIT_PER_MINUTE = int(os.getenv("RATE_LIMIT_PER_MINUTE", 120))
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
DEPENDENCY_CHECK_TIMEOUT = float(os.getenv("DEPENDENCY_CHECK_TIMEOUT", 5.0))
# Module git đang tạm dừng phát triển; tắt qua env để không mount/khởi tạo repo và ẩn các endpoint /git/*.
GIT_MODULE_ENABLED = os.getenv("GIT_MODULE_ENABLED", "true").strip().lower() == "true"

# --- Initialize Global Objects ---
if not GIT_MODULE_ENABLED:
    logger.info("GIT_MODULE_ENABLED=false: bỏ qua khởi tạo Git repo, các endpoint /git/* sẽ trả 404.")
    repo = None
else:
    try:
        repo = git.Repo(PROJECT_PATH)
    except git.InvalidGitRepositoryError:
        logger.error(f"Git repository not found at '{PROJECT_PATH}'. Please ensure the volume is mounted correctly.")
        repo = None
    except Exception as e:
        logger.error(f"Failed to initialize Git repo on startup: {e}", exc_info=True)
        repo = None

app = FastAPI(title="AI Developer Agent Service")

if ALLOWED_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_methods=["GET", "POST"],
        allow_headers=[API_KEY_HEADER, "Content-Type"],
    )


@app.on_event("startup")
def enforce_service_api_key():
    if not SERVICE_API_KEY:
        raise RuntimeError(
            "SERVICE_API_KEY must be set to a non-empty value. Refusing to start agent_service."
        )


@app.middleware("http")
async def require_api_key(request: Request, call_next):
    if request.url.path in EXEMPT_PATHS:
        return await call_next(request)
    if not SERVICE_API_KEY:
        logger.error("SERVICE_API_KEY is not configured for agent_service.")
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


class BranchName(BaseModel):
    name: str = Field(..., description="The name of the new git branch.", pattern=r"^[a-zA-Z0-9._-]+$")


class ConsultQuery(BaseModel):
    question: str
    limit: int = 3


@app.get("/health")
@app.get("/health/live")
def health_live():
    """Liveness: the process is up and can serve HTTP."""
    return {"status": "ok", "service": "agent_service"}


@app.get("/health/ready")
async def health_ready():
    """Readiness: git repo mounted and knowledge_service reachable."""
    checks = {"git_repo": "ok" if repo else "not_available"}

    try:
        async with httpx.AsyncClient(timeout=DEPENDENCY_CHECK_TIMEOUT) as client:
            response = await client.get(f"{KNOWLEDGE_SERVICE_URL}/health/live")
            checks["knowledge_service"] = "ok" if response.status_code == 200 else f"http_{response.status_code}"
    except httpx.HTTPError as e:
        checks["knowledge_service"] = f"unreachable: {e}"

    ready = all(value == "ok" for value in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "service": "agent_service", "checks": checks},
    )


@app.get("/")
def read_root():
    return {"message": "AI Developer Agent is running. Ready to analyze, code, and interact with Git."}


@app.get("/git/status")
def get_git_status():
    """
    Gets the status of the Git repository, similar to `git status`.
    """
    if not GIT_MODULE_ENABLED:
        raise HTTPException(status_code=404, detail="Git module is currently disabled.")
    if not repo:
        raise HTTPException(status_code=503, detail="Git repository is not available.")

    return {
        "active_branch": repo.active_branch.name,
        "is_dirty": repo.is_dirty(untracked_files=True),
        "untracked_files": repo.untracked_files,
        "changed_files": [item.a_path for item in repo.index.diff(None)],
        "staged_files": [item.a_path for item in repo.index.diff("HEAD")],
    }


@app.post("/git/branch")
def create_git_branch(branch: BranchName):
    """
    Creates and checks out a new Git branch.
    """
    if not GIT_MODULE_ENABLED:
        raise HTTPException(status_code=404, detail="Git module is currently disabled.")
    if not repo:
        raise HTTPException(status_code=503, detail="Git repository is not available.")

    branch_name = branch.name

    if branch_name in repo.heads:
        raise HTTPException(status_code=400, detail=f"Branch '{branch_name}' already exists.")

    try:
        if repo.head.is_detached:
            new_branch = repo.create_head(branch_name, repo.head.commit)
        else:
            new_branch = repo.create_head(branch_name)

        new_branch.checkout()

        return {
            "message": f"Successfully created and checked out new branch '{branch_name}'.",
            "current_branch": repo.active_branch.name,
        }
    except git.GitCommandError as e:
        logger.error(f"Git command failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"An internal Git error occurred: {e.stderr}")


@app.post("/consult")
async def consult_knowledge_base(query: ConsultQuery):
    """
    Proxies a question to the Knowledge Curator service so the agent can
    ground its actions in the project's canonical documentation before coding.
    """
    headers = {API_KEY_HEADER: SERVICE_API_KEY} if SERVICE_API_KEY else {}
    correlation_id = observability.get_correlation_id()
    if correlation_id:
        # Propagate the correlation ID so both services' logs share one trace key.
        headers[observability.REQUEST_ID_HEADER] = correlation_id
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{KNOWLEDGE_SERVICE_URL}/answer",
                json={"question": query.question, "limit": query.limit},
                headers=headers,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Knowledge service unreachable: {e}")

    return response.json()
