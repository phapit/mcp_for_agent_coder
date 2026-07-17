"""Gói ngữ cảnh (context package) cho yêu cầu từ khách hàng.

Mục tiêu chống ảo giác: agent PM/Coder/Tester chỉ được làm việc trên các
trích đoạn đặc tả truy xuất được (kèm nguồn, số dòng, điểm liên quan).
Khi không có đặc tả nào vượt ngưỡng, gói ngữ cảnh tuyên bố rõ điều đó
thay vì để agent tự suy đoán về hành vi hiện có.
"""

from __future__ import annotations

from datetime import datetime, timezone

REQUEST_TYPES = ("feature", "bug")
AGENT_ROLES = ("pm", "coder", "tester")

_TYPE_LABELS = {"feature": "Thêm/thay đổi tính năng", "bug": "Sửa lỗi"}

_COMMON_RULES = [
    "CHỈ được coi là 'hành vi hiện có' những gì xuất hiện trong các trích đoạn đặc tả bên dưới.",
    "Khi trích dẫn hành vi hiện có, phải ghi kèm nguồn dạng [n] tương ứng với trích đoạn.",
    "Nếu thông tin cần thiết KHÔNG có trong trích đoạn: ghi rõ 'chưa có đặc tả' và nêu câu hỏi cần làm rõ — tuyệt đối không bịa.",
    "Không phá vỡ các hành vi đã được đặc tả trong trích đoạn nếu yêu cầu không nói rõ phải thay đổi chúng.",
    "Không đề xuất công nghệ, thư viện hoặc luồng xử lý không xuất hiện trong trích đoạn; nếu bắt buộc cần thứ mới, đánh dấu rõ là ĐỀ XUẤT MỚI cần xác nhận.",
]

# Quy tắc đối chiếu chéo theo loại yêu cầu (docs/Huong_dan_su_dung_NotebookLM_hieu_qua.md §2).
_TYPE_RULES = {
    "feature": [
        "Đánh giá tác động trước: liệt kê component/endpoint/luồng trong trích đoạn sẽ bị ảnh hưởng bởi tính năng mới, và ràng buộc thiết kế nào trong đặc tả giới hạn cách làm.",
    ],
    "bug": [
        "Xác định hành vi ĐÚNG theo đặc tả trong trích đoạn trước khi sửa; nếu trích đoạn ghi nhận lỗi hoặc edge case tương tự, nêu rõ nguyên nhân và cách xử lý đã có.",
    ],
}

_ROLE_RULES = {
    "pm": [
        "Đối chiếu yêu cầu mới với từng trích đoạn: liệt kê điểm xung đột hoặc trùng lặp với đặc tả hiện có.",
        "Viết đặc tả cập nhật, đánh dấu rõ phần GIỮ NGUYÊN / THAY ĐỔI / MỚI, mỗi phần dẫn nguồn [n].",
    ],
    "coder": [
        "Xác định phạm vi thay đổi dựa trên tài liệu bị ảnh hưởng; ngoài phạm vi đó thì không sửa.",
        "Với mỗi thay đổi, kiểm tra nó có mâu thuẫn với hành vi trong trích đoạn nào không trước khi code.",
    ],
    "tester": [
        "Sinh test case cho hành vi mới từ yêu cầu, và regression test cho MỌI hành vi hiện có trong trích đoạn liên quan.",
        "Mỗi test case ghi rõ căn cứ: yêu cầu mới hay trích đoạn [n].",
    ],
}

_NO_SPECS_WARNING = (
    "KHÔNG tìm thấy đặc tả hiện có nào liên quan tới yêu cầu này trong kho tri thức. "
    "Hãy coi đây là phần hoàn toàn mới: KHÔNG suy đoán về hành vi hiện có, "
    "và nêu rõ những điểm cần khách hàng/PM xác nhận trước khi làm."
)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_context_package(query: str, excerpts: list[dict], retrieval_info: dict) -> dict:
    """Tổng hợp kết quả truy xuất thành gói ngữ cảnh lưu kèm yêu cầu."""
    documents: dict[str, dict] = {}
    for e in excerpts:
        doc = documents.setdefault(e["source"], {"source": e["source"], "excerpt_count": 0, "best_score": None})
        doc["excerpt_count"] += 1
        score = e.get("score")
        if score is not None and (doc["best_score"] is None or score > doc["best_score"]):
            doc["best_score"] = score

    return {
        "analyzed_at": _utc_now_iso(),
        "query": query,
        "has_related_specs": bool(excerpts),
        "warning": None if excerpts else _NO_SPECS_WARNING,
        "related_documents": sorted(
            documents.values(), key=lambda d: d["best_score"] or 0, reverse=True
        ),
        "excerpts": excerpts,
        "retrieval": retrieval_info,
    }


def render_context_markdown(request: dict, package: dict, role: str) -> str:
    """Markdown sẵn dùng để nạp thẳng vào prompt của agent theo vai trò."""
    type_label = _TYPE_LABELS.get(request.get("request_type"), request.get("request_type"))
    lines = [
        f"# Ngữ cảnh cho yêu cầu {request['request_id']}: {request['title']}",
        "",
        f"- Loại yêu cầu: {type_label}",
        f"- Dự án: {request.get('project') or '(không chỉ định)'}",
        f"- Vai trò nhận ngữ cảnh: {role}",
        f"- Phân tích lúc: {package['analyzed_at']}",
        "",
        "## Yêu cầu từ khách hàng",
        "",
        request["description"].strip(),
        "",
        "## Quy tắc bắt buộc cho agent",
        "",
    ]
    type_rules = _TYPE_RULES.get(request.get("request_type"), [])
    lines += [f"- {rule}" for rule in _COMMON_RULES + type_rules + _ROLE_RULES[role]]

    if not package["has_related_specs"]:
        lines += ["", "## Đặc tả hiện có liên quan", "", f"⚠️ {package['warning']}"]
        return "\n".join(lines) + "\n"

    doc_count = len(package["related_documents"])
    lines += ["", f"## Đặc tả hiện có liên quan ({len(package['excerpts'])} trích đoạn từ {doc_count} tài liệu)", ""]
    for index, e in enumerate(package["excerpts"], start=1):
        location = f", dòng {e['start_line']}–{e['end_line']}" if e.get("start_line") else ""
        heading = f" › {e['heading']}" if e.get("heading") else ""
        score = f"{e['score']:.3f}" if e.get("score") is not None else "?"
        lines.append(f"### [{index}] {e['source']}{heading} (độ liên quan {score}{location})")
        lines.append("")
        lines.append("```")
        lines.append((e.get("text") or "").strip())
        lines.append("```")
        lines.append("")
    return "\n".join(lines)
