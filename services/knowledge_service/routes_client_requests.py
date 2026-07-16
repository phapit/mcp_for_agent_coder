"""Yêu cầu từ khách hàng (client requests) → gói ngữ cảnh cho agent PM/Coder/Tester.

State (store, retrieval) sống ở main.py; truy cập qua `main.<attr>` tại thời
điểm request để test có thể monkeypatch trên main (vd main._retrieve).
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

import client_requests
import retrieval
from client_request_store import ClientRequestStore
from schemas import ClientRequestCreate, SearchFilters

import main

logger = logging.getLogger(__name__)
router = APIRouter()


def _require_client_request_store() -> ClientRequestStore:
    if main.client_request_store is None:
        raise HTTPException(status_code=503, detail="MongoDB client request store is not available.")
    return main.client_request_store


def _get_client_request_or_404(request_id: str) -> dict:
    record = _require_client_request_store().get(request_id)
    if record is None:
        raise HTTPException(status_code=404, detail=f"Client request '{request_id}' not found.")
    return record


def _analyze_client_request(record: dict, limit: int) -> dict:
    query_text = f"{record['title']}\n{record['description']}".strip()
    filters = SearchFilters(project=record["project"]) if record.get("project") else None
    matches, retrieval_info = main._retrieve(query_text, limit, filters)
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


@router.post("/client-requests/preview")
def preview_client_request(payload: ClientRequestCreate, role: str | None = None):
    """Tra cứu thuần túy: truy xuất đặc tả liên quan, KHÔNG lưu bản ghi vào MongoDB."""
    if payload.request_type not in client_requests.REQUEST_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"request_type must be one of {list(client_requests.REQUEST_TYPES)}.",
        )
    if not payload.title.strip() or not payload.description.strip():
        raise HTTPException(status_code=422, detail="title and description must be non-empty.")
    if role is not None and role not in client_requests.AGENT_ROLES:
        raise HTTPException(
            status_code=422, detail=f"role must be one of {list(client_requests.AGENT_ROLES)}."
        )

    record = {
        "request_id": "(preview)",
        "title": payload.title.strip(),
        "description": payload.description.strip(),
        "request_type": payload.request_type,
        "project": payload.project,
    }
    package = _analyze_client_request(record, payload.limit)
    response = {"context": package}
    if role is not None:
        response["role"] = role
        response["markdown"] = client_requests.render_context_markdown(record, package, role)
    return response


@router.post("/client-requests", status_code=201)
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


@router.get("/client-requests")
def list_client_requests(limit: int = 50):
    return _require_client_request_store().list(limit=max(1, min(limit, 200)))


@router.get("/client-requests/{request_id}")
def get_client_request(request_id: str):
    return _get_client_request_or_404(request_id)


@router.get("/client-requests/{request_id}/context")
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


@router.post("/client-requests/{request_id}/reanalyze")
def reanalyze_client_request(request_id: str, limit: int = 8):
    """Chạy lại truy xuất — dùng sau khi ingest thêm/cập nhật đặc tả."""
    record = _get_client_request_or_404(request_id)
    package = _analyze_client_request(record, max(1, min(limit, 20)))
    _require_client_request_store().save_context(request_id, package)
    record["context"] = package
    return record
