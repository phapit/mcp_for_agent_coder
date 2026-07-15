# Test Report

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
