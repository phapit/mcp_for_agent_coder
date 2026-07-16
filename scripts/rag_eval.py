#!/usr/bin/env python3
"""Đánh giá chất lượng RAG của knowledge_service bằng bộ câu hỏi chuẩn.

Đo 3 nhóm chỉ số:
- retrieval_hit_rate: /search trả về đúng tài liệu nguồn kỳ vọng trong top-k.
- answer_keyword_rate: câu trả lời của /answer chứa từ khóa kỳ vọng.
- refusal_rate: câu hỏi ngoài phạm vi bị từ chối (HTTP 404 do ngưỡng điểm)
  hoặc model trả lời "không tìm thấy" — chống trả lời từ context không liên quan.

Cách chạy:
    KNOWLEDGE_URL=http://localhost:8002 SERVICE_API_KEY=... \
        python scripts/rag_eval.py [--questions eval/golden_questions.json] [--limit 3] [--skip-answer]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

KNOWLEDGE_URL = os.getenv("KNOWLEDGE_URL", "http://localhost:8002").rstrip("/")
SERVICE_API_KEY = os.getenv("SERVICE_API_KEY", "")

REFUSAL_MARKERS = [
    "không tìm thấy", "không có thông tin", "không đủ thông tin",
    "don't know", "do not know", "no information", "not in the context",
]


def _post(path: str, payload: dict, timeout: float = 120.0) -> tuple[int, dict | list | None]:
    request = urllib.request.Request(
        f"{KNOWLEDGE_URL}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-API-Key": SERVICE_API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode("utf-8"))
        except Exception:
            body = None
        return e.code, body


def evaluate_question(item: dict, limit: int, skip_answer: bool) -> dict:
    result = {"id": item["id"], "question": item["question"]}

    if item.get("expect_refusal"):
        status, body = _post("/answer", {"question": item["question"], "limit": limit})
        answer_text = (body or {}).get("answer", "") if isinstance(body, dict) else ""
        refused = status == 404 or any(marker in answer_text.lower() for marker in REFUSAL_MARKERS)
        result.update({"type": "refusal", "passed": refused, "http_status": status})
        return result

    status, matches = _post("/search", {"query": item["question"], "limit": limit})
    sources = [m.get("source", "") for m in (matches or []) if isinstance(m, dict)]
    hit = any(item["expected_source_substring"] in source for source in sources)
    result.update({"type": "retrieval", "retrieval_hit": hit, "sources": sources})

    if skip_answer:
        result["passed"] = hit
        return result

    status, body = _post("/answer", {"question": item["question"], "limit": limit})
    answer_text = (body or {}).get("answer", "") if isinstance(body, dict) else ""
    keywords = item.get("expected_keywords", [])
    keyword_hits = [kw for kw in keywords if kw.lower() in answer_text.lower()]
    result.update(
        {
            "answer_http_status": status,
            "keyword_hits": keyword_hits,
            "keyword_total": len(keywords),
            "prompt_version": (body or {}).get("prompt_version") if isinstance(body, dict) else None,
            "passed": hit and len(keyword_hits) == len(keywords) and status == 200,
        }
    )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--questions", default="eval/golden_questions.json")
    parser.add_argument("--limit", type=int, default=3)
    parser.add_argument("--skip-answer", action="store_true", help="Chỉ đo retrieval, bỏ qua bước gọi LLM.")
    args = parser.parse_args()

    if not SERVICE_API_KEY:
        print("SERVICE_API_KEY chưa được set.", file=sys.stderr)
        return 2

    with open(args.questions, encoding="utf-8") as f:
        suite = json.load(f)

    results = [evaluate_question(item, args.limit, args.skip_answer) for item in suite["questions"]]

    retrieval = [r for r in results if r.get("type") == "retrieval"]
    refusal = [r for r in results if r.get("type") == "refusal"]
    summary = {
        "total": len(results),
        "retrieval_hit_rate": (
            sum(1 for r in retrieval if r.get("retrieval_hit")) / len(retrieval) if retrieval else None
        ),
        "answer_pass_rate": (
            sum(1 for r in retrieval if r.get("passed")) / len(retrieval)
            if retrieval and not args.skip_answer
            else None
        ),
        "refusal_rate": (sum(1 for r in refusal if r["passed"]) / len(refusal) if refusal else None),
    }

    print(json.dumps({"summary": summary, "results": results}, ensure_ascii=False, indent=2))
    all_passed = all(r.get("passed", r.get("retrieval_hit", False)) for r in results)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
