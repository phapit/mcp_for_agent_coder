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

### 2026-07-16 — Chọn ngôn ngữ đầu ra khi ingest spreadsheet (per-command --language)
- `IngestSpreadsheetRequest` thêm field tùy chọn `language`; `process_spreadsheet` truyền `--language` vào `generate report` khi có.
- `--language` chỉ áp dụng khi tạo report mới; nếu tái dùng report cũ, response trả `report_reused: true` và ngôn ngữ bị bỏ qua (đã ghi rõ trong UI + tài liệu).
- Frontend: dropdown ngôn ngữ trong view Ingest Spreadsheet, hiển thị ngôn ngữ + cảnh báo tái dùng trong kết quả.
- Unit test: bổ sung 2 test (truyền `--language`, và không thêm cờ khi `language=None`) + assert `report_reused` — `test_notebooklm_service.py` 7 passed.
- Tài liệu: cập nhật `docs/NotebookLM-Spreadsheet-Ingestion.md`.

### 2026-07-16 — Endpoint tra cứu thuần túy /client-requests/preview + skill ss_pocket_docs
- Thêm `POST /client-requests/preview` (main.py): truy xuất đặc tả liên quan, trả `context` (+ `markdown` nếu có `?role=pm|coder|tester`), KHÔNG ghi vào MongoDB — tái dùng `_analyze_client_request` sẵn có.
- Unit test: 6 test mới (không lưu bản ghi, có/không markdown, validate role/request_type, cảnh báo khi không có đặc tả) — `test_client_requests.py` 14 passed.
- E2E: gọi preview với project `ss_pocket` — số bản ghi trong `/client-requests` trước/sau không đổi (3 → 3), xác nhận không lưu.
- Tạo skill `.claude/skills/ss_pocket_docs/SKILL.md`: hướng dẫn tra cứu đặc tả dự án `ss_pocket` qua endpoint preview (resolve host port động bằng `docker port` vì port không cố định), lấy markdown theo vai trò, và khi nào nên dùng `/client-requests` (lưu) thay vì preview.
- Tài liệu: cập nhật `docs/Client-Request-Context.md` (bảng endpoint + khi nào dùng preview vs lưu).

### 2026-07-16 — Xuất tài liệu NotebookLM theo prompt tự do
- `NotebookLMService.generate_custom_report(prompt, output_name, report_format, language, append)`: gọi `generate report [prompt] --format ...` trên source có sẵn trong notebook (không thêm source mới), luôn generate mới (không tái dùng report cũ).
- Endpoint mới `POST /notebook-reports` (main.py) — resolve project/env như `/ingest-spreadsheet`, validate `format` (briefing-doc/study-guide/blog-post/custom), `append` chỉ áp dụng khi format khác `custom`, hỗ trợ `language` per-command (tái dùng field đã thêm trước đó). Ghi manifest + trigger auto_ingest.
- Frontend: view mới "Xuất tài liệu theo yêu cầu" (`/custom-report`) — prompt tự do, chọn định dạng/ngôn ngữ/append.
- Unit test: 6 test mới trong `test_notebooklm_service.py` (generate/wait/download, truyền format+language+append, append bị bỏ qua khi format=custom, validate prompt/notebook_id) — 13 passed.
- Validation qua HTTP thật: format sai → 422, project không tồn tại → 404, prompt rỗng → 422. Chưa gọi NotebookLM thật (tránh tốn quota/tạo artifact thật không cần thiết).
- Tài liệu: thêm mục trong `docs/NotebookLM-Spreadsheet-Ingestion.md`, cập nhật README.md.

### 2026-07-16 — Giới hạn độ dài prompt cho /notebook-reports (tối đa 1024 ký tự)
- `NotebookReportRequest.validate_prompt` (main.py) chặn prompt > 1024 ký tự, trả 422 kèm số ký tự thực tế.
- Frontend: `maxlength="1024"` trên textarea + bộ đếm ký tự + kiểm tra lại trước khi submit.
- Unit test: `test_notebook_report_request.py` (mới) — chấp nhận đúng 1024, từ chối 1025, endpoint trả 422 qua TestClient — 3 passed.
- Xác nhận qua HTTP thật: 1025 ký tự → 422 đúng thông báo; 1024 ký tự qua được validate (tiếp tục xử lý bình thường).

### 2026-07-16 — Tái cấu trúc main.py của knowledge_service (1656 → ~340 dòng)
- Tách theo domain: `schemas.py` (Pydantic models + validators), `routes_ingest.py` (/ingest*), `routes_qa.py` (/search /answer /sessions), `routes_client_requests.py` (/client-requests*), `routes_notebooklm.py` (/ingest-excel* /ingest-spreadsheet /notebook-reports /project-notebook-configs*).
- `main.py` giữ vai trò composition root: config env, khởi tạo client/store toàn cục, middleware (API key, rate limit, body size, correlation), lifecycle, health check, include routers.
- QUY ƯỚC STATE (ghi trong docstring main.py): routes_* truy cập state qua `main.<attr>` tại thời điểm request — nhờ đó test monkeypatch trên main tác động mọi domain; cross-domain gọi qua alias `main._retrieve` / `main._trigger_auto_ingest`, không import chéo router.
- Thêm tính năng mới = thêm 1 file `routes_*` + `app.include_router(...)` trong main.py.
- Kiểm chứng: 98 passed (y hệt baseline trước refactor, 8 fail sẵn có trong test_ingest_sync không đổi); openapi có đúng 26 paths như trước; smoke test HTTP thật cả 4 router + auth 401.
