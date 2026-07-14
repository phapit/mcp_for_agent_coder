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

### 2026-07-14 18:xx — NotebookLM Spreadsheet Ingestion - MVP
- Thêm adapter `services/knowledge_service/notebooklm_service.py` sử dụng CLI `notebooklm-py`.
- Thêm `POST /ingest-spreadsheet` để nhận Google Spreadsheet URL, tạo report và lưu Markdown local.
- Dùng cố định `NOTEBOOKLM_NOTEBOOK_ID`; ghi `source_id`, `artifact_id` và output vào manifest.
- Sửa lỗi response bất đồng bộ: hỗ trợ `task_id` và gọi `artifact wait` trước khi download report.
- Thêm unit test cho response dạng `artifact_id` và `task_id`.
- Tài liệu vận hành: `docs/NotebookLM-Spreadsheet-Ingestion.md`.
- Smoke test adapter: pass. Kiểm tra cú pháp Python và Docker Compose config: pass.
- Unit test đầy đủ qua pytest chưa chạy được trên host do thiếu `openpyxl`/`python3-venv`; cần xác nhận trong Docker hoặc môi trường Python đầy đủ.
