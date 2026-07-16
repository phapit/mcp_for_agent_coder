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

### 2026-07-15 21:xx — Project Notebook Config + MongoDB
- Thêm MongoDB service vào `docker-compose.yml` và cấu hình `MONGODB_URI`, `MONGODB_DB_NAME`.
- Tạo `services/knowledge_service/project_config_store.py` để lưu cấu hình `project_name + notebook_env`.
- Thêm API CRUD `/project-notebook-configs*` cho phép cài đặt `notebook_id` và `notebooklm_auth_name` theo từng env của project.
- Sửa `POST /ingest-spreadsheet` để chỉ cần `project_name`, `notebook_env`, `spreadsheet_id`, `output_name`.
- Đọc auth JSON từ folder `NOTEBOOKLM_AUTH_DIR`, không còn phụ thuộc `NOTEBOOKLM_NOTEBOOK_ID` cố định.
- Lưu Markdown và manifest theo sub-directory `docs/imported/<project_name>/`.
- Thêm unit test cho `ProjectConfigStore` và cập nhật test `NotebookLMService` cho auth JSON bắt buộc.
- Thêm script CLI `scripts/import_project_config.py` để import nhanh cấu hình project/env khi chưa có UI.

### 2026-07-15 12:25 — Shared API Key Guard
- Task `Shared API Key Config - Task 1`: thêm `SERVICE_API_KEY` vào `.env` và truyền vào `knowledge_service`, `agent_service` qua `docker-compose.yml`.
- Task `Knowledge Service Auth Guard - Task 2`: thêm middleware kiểm tra header `X-API-Key` cho toàn bộ endpoint của `knowledge_service`, miễn trừ `/health`.
- Task `Agent Service Auth Guard - Task 3`: thêm middleware kiểm tra header `X-API-Key` cho toàn bộ endpoint của `agent_service`, miễn trừ `/health`.
- Task `API Key Verification Tests - Task 4`: thêm test API cho 2 service và bổ sung `pytest` vào `services/agent_service/requirements.txt`.
- Smoke test:
  - `docker compose up -d --build knowledge_service agent_service`: pass.
  - `curl http://127.0.0.1:8000/health`: pass.
  - `curl http://127.0.0.1:8001/health`: pass.
  - `curl http://127.0.0.1:8001/`: trả `503` đúng kỳ vọng khi `SERVICE_API_KEY` chưa được điền trong `.env`.
- Unit test:
  - `docker compose exec knowledge_service pytest tests/test_api_key_auth.py`: pass.
  - `docker compose exec agent_service pytest tests/test_api_key_auth.py`: pass.

### 2026-07-15 — Kafka foundation và document identity
- Chốt kiến trúc event-driven sử dụng Kafka ở Compose riêng.
- Tạo `services/knowledge_service/job_contracts.py` với event schema version 1 và các trạng thái job.
- Tạo `services/knowledge_service/job_store.py` để quản lý state job bước đầu.
- Tạo `services/knowledge_service/document_identity.py` với document ID, chunk ID và content hash ổn định.
- Unit test: `2 passed` cho job contract/store và `3 passed` cho document identity.
- Smoke test: `python3 -m py_compile` pass.
- Chưa triển khai Kafka worker thực tế trong task này.

### 2026-07-15 — Loại bỏ API key hardcode khỏi CLI scripts
- Sửa `scripts/import_project_config.py` và `scripts/ingest_spreadsheet.py`.
- Hai script đọc `SERVICE_API_KEY` từ environment và gửi qua header `X-API-Key`.
- Khi thiếu biến môi trường, script trả lỗi rõ ràng và exit code `2`.
- Smoke test compile pass.
- Smoke test thiếu `SERVICE_API_KEY`: cả hai script trả exit code `2` đúng kỳ vọng.

### 2026-07-15 — NotebookLM resume artifact và chống tạo trùng
- `NotebookLMService` kiểm tra `source list --json` trước `source add-drive`.
- Kiểm tra `artifact list --type report --json` trước `generate report`.
- Tái sử dụng source/artifact đã tồn tại và dùng `artifact wait` trước khi download.
- Phân loại `RateLimitError` thành `NotebookLMRateLimitError`.
- Endpoint `/ingest-spreadsheet` trả HTTP `429` khi NotebookLM rate limit, không retry ngay.
- Bổ sung unit test cho source/artifact reuse.
- Unit test NotebookLM: `6 passed`.

### 2026-07-16 — Yêu cầu khách hàng → gói ngữ cảnh cho agent PM/Coder/Tester
- Tạo `services/knowledge_service/client_requests.py` (dựng gói ngữ cảnh + render markdown theo vai trò, quy tắc chống ảo giác) và `client_request_store.py` (MongoDB collection `client_requests`).
- 5 endpoint mới trên `knowledge_service`: `POST /client-requests`, `GET /client-requests`, `GET /client-requests/{id}`, `GET /client-requests/{id}/context?role=pm|coder|tester`, `POST /client-requests/{id}/reanalyze`.
- Frontend: view "Yêu cầu khách hàng" (`/client-requests`) — form gửi, danh sách, chi tiết trích đoạn, tab vai trò, nút sao chép markdown và phân tích lại.
- Bật `RERANK_ENABLED=1` trong `.env`: bắt buộc để truy vấn tiếng Việt khớp đặc tả tiếng Anh (reranker mmarco đa ngôn ngữ); không bật thì truy vấn tiếng Việt không vượt ngưỡng điểm.
- Unit test: `tests/test_client_requests.py` — `8 passed`; toàn suite 82 passed (8 fail sẵn có trong `test_ingest_sync.py`, không liên quan).
- E2E: tạo yêu cầu "Session tự gia hạn…" → truy xuất 8 trích đoạn từ 7 file `app_backend_specification_part*.md`.
- Tài liệu chi tiết: `docs/Client-Request-Context.md`.
