"""Hybrid retrieval + endpoints /search, /answer, /sessions.

State (clients, config) sống ở main.py (composition root); mọi truy cập đều
qua `main.<attr>` tại thời điểm request để test có thể monkeypatch trên main.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, HTTPException
from qdrant_client.http.models import FieldCondition, Filter, MatchText, MatchValue

import guardrails
import observability
import prompts
import retrieval
from schemas import AnswerQuery, SearchFilters, SearchQuery
from session_store import history_messages

import main

logger = logging.getLogger(__name__)
router = APIRouter()


def _build_search_filter(filters: SearchFilters | None) -> Filter | None:
    if filters is None:
        return None
    conditions = [
        FieldCondition(key=field, match=MatchValue(value=value))
        for field, value in filters.model_dump().items()
        if value is not None
    ]
    return Filter(must=conditions) if conditions else None


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
    query_vector = main.embeddings.embed_query(query)
    results = main.qdrant_client.query_points(
        collection_name=main.COLLECTION_NAME,
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
        points, _ = main.qdrant_client.scroll(
            collection_name=main.COLLECTION_NAME,
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
    if not main.embeddings or not main.qdrant_client:
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
    rerank_pool = limit * 2 if main.reranker else limit
    fused = retrieval.fuse_candidates(dense, keyword, limit=max(rerank_pool, limit))

    rerank_started = time.perf_counter()
    reranked = bool(main.reranker) and main.reranker.rerank(query, fused)
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


@router.post("/search")
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


@router.post("/answer")
def get_answer(answer_query: AnswerQuery):
    use_online = answer_query.use_online_model == 1
    client, model = main._select_chat_client(answer_query.use_online_model)

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
    if answer_query.session_id and main.session_store is not None:
        # Insert prior turns between the system message (if any) and the final user message.
        turns = main.session_store.get_turns(answer_query.session_id, main.SESSION_CONTEXT_TURNS)
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
    if answer_query.session_id and main.session_store is not None:
        try:
            main.session_store.append_turn(answer_query.session_id, answer_query.question, answer_text)
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


@router.get("/sessions/{session_id}")
def get_session(session_id: str):
    if main.session_store is None:
        raise HTTPException(status_code=503, detail="MongoDB session store is not available.")
    session = main.session_store.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return session


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str):
    if main.session_store is None:
        raise HTTPException(status_code=503, detail="MongoDB session store is not available.")
    if not main.session_store.delete_session(session_id):
        raise HTTPException(status_code=404, detail=f"Session '{session_id}' not found.")
    return {"deleted": True, "session_id": session_id}
