import retrieval
from retrieval import (
    apply_threshold,
    bm25_scores,
    fuse_candidates,
    query_terms,
    relevance_score,
    rrf_fuse,
    tokenize,
)


def _candidate(cid, text="nội dung", vector_score=None, keyword_score=None):
    return {
        "id": cid,
        "text": text,
        "source": f"/docs/{cid}.md",
        "heading": "H",
        "start_line": 1,
        "end_line": 2,
        "vector_score": vector_score,
        "keyword_score": keyword_score,
    }


def test_tokenize_handles_vietnamese():
    assert "kiến" in tokenize("Kiến trúc hệ thống")


def test_query_terms_drops_stopwords_and_dedups():
    terms = query_terms("Session là gì và session kéo dài bao lâu")
    assert "session" in terms
    assert "là" not in terms and "gì" not in terms
    assert terms.count("session") == 1


def test_bm25_prefers_matching_document():
    texts = [
        "session duration is 28 days for all users",
        "kafka topics are created at startup",
        "the login screen shows an error",
    ]
    scores = bm25_scores(["session", "duration"], texts)
    assert scores[0] > scores[1]
    assert scores[0] > scores[2]


def test_rrf_rewards_presence_in_both_rankings():
    fused = rrf_fuse([["a", "b", "c"], ["b", "d"]], k=1)
    assert fused["b"] > fused["a"]
    assert fused["b"] > fused["d"]


def test_fuse_candidates_merges_scores():
    dense = [_candidate("x", vector_score=0.8), _candidate("y", vector_score=0.5)]
    keyword = [_candidate("x", keyword_score=3.0), _candidate("z", keyword_score=2.9)]
    fused = fuse_candidates(dense, keyword, limit=10)

    by_id = {c["id"]: c for c in fused}
    assert by_id["x"]["vector_score"] == 0.8
    assert by_id["x"]["keyword_score"] == 3.0
    assert fused[0]["id"] == "x"  # found by both retrievers -> ranked first


def test_fuse_candidates_gates_weak_keyword_only_matches():
    dense = [_candidate("a", vector_score=0.9)]
    keyword = [_candidate("strong", keyword_score=10.0), _candidate("weak", keyword_score=1.0)]
    fused = fuse_candidates(dense, keyword, limit=10, keyword_only_min_ratio=0.5)
    ids = [c["id"] for c in fused]
    assert "strong" in ids
    assert "weak" not in ids  # below half the best keyword score, dense never saw it


def test_apply_threshold_uses_dense_floor(monkeypatch):
    monkeypatch.setattr(retrieval, "MIN_SCORE_THRESHOLD", 0.5)
    candidates = [_candidate("hi", vector_score=0.7), _candidate("lo", vector_score=0.2)]
    kept = apply_threshold(candidates, use_rerank_floor=False)
    assert [c["id"] for c in kept] == ["hi"]


def test_apply_threshold_uses_rerank_floor(monkeypatch):
    monkeypatch.setattr(retrieval, "MIN_RERANK_SCORE", 0.4)
    good = _candidate("good", vector_score=0.1)
    good["rerank_score"] = 0.9
    bad = _candidate("bad", vector_score=0.9)
    bad["rerank_score"] = 0.1
    kept = apply_threshold([good, bad], use_rerank_floor=True)
    assert [c["id"] for c in kept] == ["good"]


def test_relevance_score_prefers_rerank():
    candidate = _candidate("c", vector_score=0.9)
    assert relevance_score(candidate) == 0.9
    candidate["rerank_score"] = 0.2
    assert relevance_score(candidate) == 0.2
