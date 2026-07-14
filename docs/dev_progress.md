# Dev Progress

### 2026-07-14 12:xx — Knowledge Service scaffold - Task 1
- Tạo `services/knowledge_service/{main.py,requirements.txt,Dockerfile}`.
- Cài đặt `/ingest`, `/search`, `/answer` (trước đó là stub `pass`).
- Smoke test: `python -m py_compile` pass (không thể chạy uvicorn/tải model trong sandbox này — không có Docker/mạng ra ngoài).

### 2026-07-14 12:xx — Agent Service scaffold - Task 2
- Tạo `services/agent_service/{main.py,requirements.txt,Dockerfile}`.
- Giữ nguyên `/git/status`, `/git/branch` từ `main.py` cũ.
- Thêm `/consult` để proxy câu hỏi sang `knowledge_service`.
- Smoke test: `python -m py_compile` pass.

### 2026-07-14 12:xx — Dọn dẹp root
- Xóa `main.py`, `Dockerfile`, `requirements.txt` ở root (dead code, không còn được `docker-compose.yml` tham chiếu).

## Còn thiếu / chưa làm trong phiên này
- Chưa chạy `docker compose up` thực tế để xác nhận build + kết nối Qdrant (giới hạn sandbox, không có Docker).
- Chưa có `.env`/`env_file` để truyền `OPENAI_API_KEY` vào container.
- Chưa viết unit test (pytest) cho 2 service — cần Tester subagent đảm nhiệm ở Giai đoạn 3.
- 4 file doc placeholder (`Database-Design.md`, `Business-Rules.md`, `Coding-Convention.md`, `Postmortems.md`) vẫn trống, cần Pháp bổ sung nội dung nghiệp vụ thực tế trước khi ingest có ý nghĩa.
