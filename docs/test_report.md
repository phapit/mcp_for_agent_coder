# Test Report

### 2026-07-15 — Kafka foundation, document identity và CLI API key
- Phạm vi:
  - `services/knowledge_service/job_contracts.py`
  - `services/knowledge_service/job_store.py`
  - `services/knowledge_service/document_identity.py`
  - `services/knowledge_service/tests/test_job_contracts.py`
  - `services/knowledge_service/tests/test_document_identity.py`
  - `scripts/import_project_config.py`
  - `scripts/ingest_spreadsheet.py`
- Unit test:
  - Job contract/store: `2 passed`.
  - Document identity: `3 passed`.
- Smoke test:
  - `python3 -m py_compile`: pass.
  - Thiếu `SERVICE_API_KEY` ở hai CLI script: exit code `2`, thông báo lỗi đúng kỳ vọng.
- Adversarial/integration test Kafka: chưa thực hiện; Kafka nằm ở Compose riêng và worker chưa hoàn tất.

### 2026-07-15 — NotebookLM artifact reuse và rate limit
- Phạm vi:
  - `services/knowledge_service/notebooklm_service.py`
  - `services/knowledge_service/main.py`
  - `services/knowledge_service/tests/test_notebooklm_service.py`
- Unit test: `6 passed`.
- Đã kiểm thử source/artifact đã tồn tại không tạo mới.
- Đã phân loại `RateLimitError` thành HTTP `429`.
- Smoke test `py_compile`: pass.
- Chưa có integration test trực tiếp với NotebookLM production account.

### 2026-07-15 21:xx
- Phạm vi:
  - `services/knowledge_service/project_config_store.py`
  - `services/knowledge_service/notebooklm_service.py`
  - `services/knowledge_service/main.py`
  - `docker-compose.yml`
- Bug phát hiện trong lúc phát triển: 2
- Bug đã sửa: 2

Chi tiết:
- Lỗi 1: `NotebookLMService` chưa chặn trường hợp thiếu `NOTEBOOKLM_AUTH_JSON` khi bỏ cấu hình env cố định.
  - Root cause: MVP cũ giả định auth luôn tồn tại trong `.env`.
  - Cách sửa: thêm validate bắt buộc `auth_json` trước khi gọi CLI và cập nhật unit test.
- Lỗi 2: `NOTEBOOKLM_AUTH_JSON` có thể làm bẩn process env sau khi chạy CLI.
  - Root cause: gán env tạm thời nhưng chưa khôi phục an toàn nếu runner lỗi.
  - Cách sửa: bọc restore env trong `try/finally`.

Kết quả test:
- Unit test mục tiêu: đã bổ sung.
- Smoke test local:
  - `python -m py_compile` sẽ được chạy sau khi hoàn tất patch.
  - `pytest` sẽ được chạy nếu môi trường local hiện tại có đủ dependency.
- Chưa có adversarial test subagent độc lập trong phiên này.

### 2026-07-15 12:25
- Phạm vi:
  - `services/knowledge_service/main.py`
  - `services/agent_service/main.py`
  - `services/knowledge_service/tests/test_api_key_auth.py`
  - `services/agent_service/tests/test_api_key_auth.py`
  - `docker-compose.yml`
  - `.env`
- Bug phát hiện trong lúc phát triển: 2
- Bug đã sửa: 2

Chi tiết:
- Lỗi 1: Toàn bộ API chưa có lớp bảo vệ chung bằng key.
  - Root cause: service chỉ dùng API key cho provider AI, chưa có auth guard ở biên API FastAPI.
  - Cách sửa: thêm middleware `X-API-Key` dùng chung với biến môi trường `SERVICE_API_KEY`, miễn trừ `/health`.
- Lỗi 2: `agent_service` khi gọi nội bộ sang `knowledge_service` sẽ bị chặn nếu không forward shared key.
  - Root cause: proxy `/consult` trước đó chỉ forward JSON body, chưa truyền credential nội bộ.
  - Cách sửa: thêm header `X-API-Key` khi `agent_service` gọi `knowledge_service`.

Kết quả test:
- Unit test:
  - `docker compose exec knowledge_service pytest tests/test_api_key_auth.py`: 3 passed.
  - `docker compose exec agent_service pytest tests/test_api_key_auth.py`: 3 passed.
- Smoke test local:
  - `docker compose up -d --build knowledge_service agent_service`: pass.
  - `curl http://127.0.0.1:8000/health`: `200 OK`.
  - `curl http://127.0.0.1:8001/health`: `200 OK`.
  - `curl http://127.0.0.1:8001/`: `503 SERVICE_API_KEY is not configured.` đúng kỳ vọng với `.env` hiện đang để trống.
- Chưa có adversarial test subagent độc lập trong phiên này.
