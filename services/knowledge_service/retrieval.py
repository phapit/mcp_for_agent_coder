"""Hybrid retrieval: dense vector search + keyword (BM25) search fused with RRF,
optional cross-encoder reranking, and a minimum relevance threshold.

Addresses the postmortem where pure semantic search returned the wrong context:
keyword recall catches exact-term matches the embedding misses, the reranker
re-scores query/chunk pairs jointly, and the threshold refuses low-relevance
context instead of letting the LLM answer from noise.
"""

from __future__ import annotations

import logging
import math
import os
import re
import threading

logger = logging.getLogger(__name__)

HYBRID_SEARCH_ENABLED = os.getenv("HYBRID_SEARCH_ENABLED", "1") == "1"
RERANK_ENABLED = os.getenv("RERANK_ENABLED", "0") == "1"
RERANK_MODEL = os.getenv("RERANK_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2")
# Cosine similarity floor for dense matches (all-MiniLM cosine; tune via eval set).
MIN_SCORE_THRESHOLD = float(os.getenv("MIN_SCORE_THRESHOLD", 0.35))
# Probability floor (sigmoid of cross-encoder logit) when the reranker is on.
MIN_RERANK_SCORE = float(os.getenv("MIN_RERANK_SCORE", 0.3))
# How many candidates each retriever contributes before fusion.
CANDIDATE_POOL_MULTIPLIER = int(os.getenv("CANDIDATE_POOL_MULTIPLIER", 4))
RRF_K = int(os.getenv("RRF_K", 60))

_TOKEN_RE = re.compile(r"\w+", re.UNICODE)
_STOPWORDS = {
    # English
    "the", "a", "an", "is", "are", "was", "were", "of", "in", "on", "for", "to",
    "and", "or", "what", "how", "why", "when", "where", "which", "who", "does", "do",
    # Vietnamese (single syllables common in questions)
    "là", "gì", "của", "và", "có", "không", "như", "nào", "cho", "được", "trong",
    "với", "các", "những", "một", "này", "đó", "thì", "để", "khi", "ra", "sao",
}


def tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


def query_terms(query: str, max_terms: int = 8) -> list[str]:
    """Meaningful search terms: deduplicated, stopwords removed, short tokens dropped."""
    terms: list[str] = []
    for token in tokenize(query):
        if len(token) < 2 or token in _STOPWORDS or token in terms:
            continue
        terms.append(token)
    return terms[:max_terms]


def bm25_scores(terms: list[str], texts: list[str], k1: float = 1.5, b: float = 0.75) -> list[float]:
    """BM25 over the candidate pool (the pool itself serves as the corpus for IDF)."""
    if not terms or not texts:
        return [0.0] * len(texts)
    docs = [tokenize(text) for text in texts]
    n = len(docs)
    avgdl = sum(len(d) for d in docs) / n if n else 1.0
    scores = [0.0] * n
    for term in terms:
        df = sum(1 for d in docs if term in d)
        if df == 0:
            continue
        idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
        for i, d in enumerate(docs):
            tf = d.count(term)
            if tf == 0:
                continue
            dl = len(d) or 1
            scores[i] += idf * (tf * (k1 + 1)) / (tf + k1 * (1 - b + b * dl / avgdl))
    return scores


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion: id -> sum over rankings of 1/(k + rank)."""
    fused: dict[str, float] = {}
    for ranking in rankings:
        for rank, item_id in enumerate(ranking, start=1):
            fused[item_id] = fused.get(item_id, 0.0) + 1.0 / (k + rank)
    return fused


def fuse_candidates(
    dense: list[dict],
    keyword: list[dict],
    limit: int,
    rrf_k: int = RRF_K,
    keyword_only_min_ratio: float = 0.5,
) -> list[dict]:
    """Merge dense and keyword candidate lists into one ranked list.

    Each candidate dict must carry a unique "id". Dense candidates carry
    "vector_score"; keyword candidates carry "keyword_score". A candidate found
    only by keywords must score at least keyword_only_min_ratio of the best
    keyword score, so a stray term match cannot sneak into the context.
    """
    by_id: dict[str, dict] = {}
    for item in dense + keyword:
        merged = by_id.setdefault(item["id"], dict(item))
        merged.update({k: v for k, v in item.items() if v is not None})

    top_keyword = max((c.get("keyword_score") or 0.0 for c in keyword), default=0.0)
    fused = rrf_fuse(
        [[c["id"] for c in dense], [c["id"] for c in keyword]],
        k=rrf_k,
    )

    results = []
    for item_id, fused_score in sorted(fused.items(), key=lambda kv: kv[1], reverse=True):
        candidate = by_id[item_id]
        if candidate.get("vector_score") is None:
            kw = candidate.get("keyword_score") or 0.0
            if top_keyword <= 0 or kw < keyword_only_min_ratio * top_keyword:
                continue
        candidate["fused_score"] = fused_score
        results.append(candidate)
        if len(results) >= limit:
            break
    return results


def relevance_score(candidate: dict) -> float:
    """The score the threshold applies to: rerank probability when present, else cosine."""
    if candidate.get("rerank_score") is not None:
        return candidate["rerank_score"]
    return candidate.get("vector_score") or 0.0


def apply_threshold(candidates: list[dict], use_rerank_floor: bool) -> list[dict]:
    floor = MIN_RERANK_SCORE if use_rerank_floor else MIN_SCORE_THRESHOLD
    kept = []
    for candidate in candidates:
        if candidate.get("rerank_score") is None and candidate.get("vector_score") is None:
            # Keyword-only match without reranker confirmation already passed the
            # keyword-ratio gate in fuse_candidates; keep it.
            kept.append(candidate)
        elif relevance_score(candidate) >= floor:
            kept.append(candidate)
    return kept


class Reranker:
    """Lazy-loaded cross-encoder; falls back to no-op if the model is unavailable."""

    def __init__(self, model_name: str = RERANK_MODEL):
        self.model_name = model_name
        self._model = None
        self._failed = False
        self._lock = threading.Lock()

    def _load(self):
        if self._model is not None or self._failed:
            return self._model
        with self._lock:
            if self._model is None and not self._failed:
                try:
                    from sentence_transformers import CrossEncoder

                    self._model = CrossEncoder(self.model_name)
                    logger.info(f"Loaded reranker model '{self.model_name}'.")
                except Exception as e:
                    self._failed = True
                    logger.error(f"Reranker '{self.model_name}' unavailable, skipping rerank: {e}")
        return self._model

    def rerank(self, query: str, candidates: list[dict]) -> bool:
        """Set candidate['rerank_score'] (sigmoid probability) and re-sort in place.

        Returns True when reranking actually ran.
        """
        model = self._load()
        if model is None or not candidates:
            return False
        logits = model.predict([(query, c["text"]) for c in candidates])
        for candidate, logit in zip(candidates, logits):
            candidate["rerank_score"] = 1.0 / (1.0 + math.exp(-float(logit)))
        candidates.sort(key=lambda c: c["rerank_score"], reverse=True)
        return True
