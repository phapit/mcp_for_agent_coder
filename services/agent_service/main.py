import os
import logging
import secrets

import httpx
import git
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
PROJECT_PATH = os.getenv("PROJECT_PATH", "/app/project_data")
KNOWLEDGE_SERVICE_URL = os.getenv("KNOWLEDGE_SERVICE_URL", "http://knowledge_service:8000")
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY", "").strip()
API_KEY_HEADER = "X-API-Key"
EXEMPT_PATHS = {"/health"}

# --- Initialize Global Objects ---
try:
    repo = git.Repo(PROJECT_PATH)
except git.InvalidGitRepositoryError:
    logger.error(f"Git repository not found at '{PROJECT_PATH}'. Please ensure the volume is mounted correctly.")
    repo = None
except Exception as e:
    logger.error(f"Failed to initialize Git repo on startup: {e}", exc_info=True)
    repo = None

app = FastAPI(title="AI Developer Agent Service")


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


class BranchName(BaseModel):
    name: str = Field(..., description="The name of the new git branch.", pattern=r"^[a-zA-Z0-9._-]+$")


class ConsultQuery(BaseModel):
    question: str
    limit: int = 3


@app.get("/health")
def health_check():
    return {"status": "ok", "service": "agent_service"}


@app.get("/")
def read_root():
    return {"message": "AI Developer Agent is running. Ready to analyze, code, and interact with Git."}


@app.get("/git/status")
def get_git_status():
    """
    Gets the status of the Git repository, similar to `git status`.
    """
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
    async with httpx.AsyncClient(timeout=60.0) as client:
        try:
            response = await client.post(
                f"{KNOWLEDGE_SERVICE_URL}/answer",
                json={"question": query.question, "limit": query.limit},
                headers={API_KEY_HEADER: SERVICE_API_KEY} if SERVICE_API_KEY else {},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=e.response.status_code, detail=e.response.text)
        except httpx.RequestError as e:
            raise HTTPException(status_code=503, detail=f"Knowledge service unreachable: {e}")

    return response.json()
