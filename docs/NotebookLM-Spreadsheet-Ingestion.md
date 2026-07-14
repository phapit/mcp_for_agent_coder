# NotebookLM Spreadsheet Ingestion

## Mục đích

Tính năng này chuyển nội dung từ Google Spreadsheet thành Markdown thông qua
NotebookLM và lưu kết quả vào thư mục local của project. Giải pháp không cần
OpenAI API Key hoặc Claude API Key.

## Kiến trúc MVP

```text
Google Spreadsheet URL
        |
        v
notebooklm source add
        |
        v
notebooklm source wait
        |
        v
notebooklm generate report
        |
        v
notebooklm artifact wait
        |
        v
notebooklm download report
        |
        v
docs/imported/<output_name>.md
```

MVP sử dụng một NotebookLM notebook cố định qua `NOTEBOOKLM_NOTEBOOK_ID`. Mỗi
request bổ sung Spreadsheet vào notebook chung và tạo một report Markdown mới.

## Cấu hình

Các biến cần thiết trong `.env`:

```env
NOTEBOOKLM_NOTEBOOK_ID=<notebook-id>
NOTEBOOKLM_AUTH_JSON=<storage-state-json>
```

`NOTEBOOKLM_AUTH_JSON` chứa Google session cookie của `notebooklm-py` và không
được ghi vào tài liệu, commit vào Git hoặc đưa vào log.

Tài khoản Google trong session phải có quyền đọc Spreadsheet và quyền truy cập
NotebookLM notebook.

## API

Endpoint:

```http
POST /ingest-spreadsheet
Content-Type: application/json
```

Request:

```json
{
  "spreadsheet_url": "https://docs.google.com/spreadsheets/d/<ID>/edit",
  "output_name": "requirements.md"
}
```

`output_name` chỉ được là tên file Markdown đơn giản, không chứa path hoặc thư
mục con.

Response thành công gồm:

```json
{
  "spreadsheet_url": "https://docs.google.com/spreadsheets/d/<ID>/edit",
  "notebook_id": "<notebook-id>",
  "source_id": "<source-id>",
  "artifact_id": "<artifact-id>",
  "output_md": "/app/project_data/docs/imported/requirements.md"
}
```

## Chạy kiểm thử thực tế

Build và khởi động service:

```bash
docker compose build knowledge_service
docker compose up -d knowledge_service
```

Kiểm tra xác thực NotebookLM:

```bash
docker compose exec knowledge_service notebooklm auth check --test --json
```

Gọi API:

```bash
curl -X POST http://localhost:8000/ingest-spreadsheet \
  -H "Content-Type: application/json" \
  -d '{
    "spreadsheet_url": "https://docs.google.com/spreadsheets/d/<ID>/edit",
    "output_name": "test-spreadsheet.md"
  }'
```

Kết quả nằm trong `docs/imported/test-spreadsheet.md`. Metadata của lần xử lý
nằm trong `docs/imported/.manifest.json`.

## Xử lý lỗi report generation

NotebookLM generation là thao tác bất đồng bộ. Một số phiên bản CLI trả về
`task_id` thay vì `artifact_id` sau lệnh `generate report`. Adapter trong
`services/knowledge_service/notebooklm_service.py` hỗ trợ cả hai dạng, sau đó
luôn gọi `artifact wait` trước khi tải report.

Lỗi phổ biến:

- `NOTEBOOKLM_NOTEBOOK_ID is not configured`: thiếu notebook ID.
- Lỗi xác thực `401`/`403`: session Google hết hạn, cần đăng nhập lại bằng
  `notebooklm login` và cập nhật `NOTEBOOKLM_AUTH_JSON`.
- Lỗi quyền Spreadsheet: tài khoản trong NotebookLM session không có quyền đọc
  Spreadsheet.
- Report chưa hoàn tất: kiểm tra log service và trạng thái artifact trong
  notebook.

## Các file liên quan

- `services/knowledge_service/notebooklm_service.py`: adapter gọi NotebookLM.
- `services/knowledge_service/main.py`: endpoint `/ingest-spreadsheet`.
- `services/knowledge_service/manifest.py`: lưu metadata xử lý.
- `services/knowledge_service/tests/test_notebooklm_service.py`: unit test
  adapter với response `artifact_id` và `task_id`.
- `docker-compose.yml`: truyền cấu hình NotebookLM vào container.

## Giới hạn MVP

- Dùng chung một notebook cho mọi request nên source có thể tích lũy và có thể
  bị trùng nếu gửi lại cùng URL.
- Chưa hỗ trợ truyền `notebook_id` động theo từng request.
- `notebooklm-py` là thư viện không chính thức và phụ thuộc API nội bộ của
  NotebookLM.
- Việc tạo report là synchronous ở endpoint MVP; request có thể mất thời gian
  khi NotebookLM xử lý Spreadsheet lớn.
