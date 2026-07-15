# NotebookLM Spreadsheet Ingestion

## Mục đích

Tính năng này chuyển nội dung từ Google Spreadsheet thành Markdown thông qua
NotebookLM và lưu kết quả vào thư mục local của project. Giải pháp không cần
OpenAI API Key hoặc Claude API Key.

## Kiến trúc hiện tại

```text
Google Spreadsheet ID
        |
        v
notebooklm source add-drive --mime-type google-sheets
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
docs/imported/<project_name>/<output_name>.md
```

Service không còn dùng `NOTEBOOKLM_NOTEBOOK_ID` cố định nữa. Thay vào đó:

- cấu hình `project_name + notebook_env` được lưu trong MongoDB
- mỗi cấu hình trỏ tới `notebook_id` và `notebooklm_auth_name`
- auth file được đọc từ thư mục local dùng chung

## Cấu hình

Các biến cần thiết trong `.env` hoặc `docker-compose.yml`:

```env
MONGODB_URI=mongodb://mongodb:27017
MONGODB_DB_NAME=knowledge_service
NOTEBOOKLM_AUTH_DIR=/app/project_data/notebooklm_auth
```

Trong `NOTEBOOKLM_AUTH_DIR`, anh tạo thủ công các file như:

- `team-a.json`
- `team-b.json`

Nội dung mỗi file là `storage_state.json` của `notebooklm-py`. Các file này
không được commit vào Git hoặc đưa vào log.

Tài khoản Google trong session phải có quyền đọc Spreadsheet và quyền truy cập
NotebookLM notebook.

## API

Endpoint:

```http
POST /ingest-spreadsheet
Content-Type: application/json
```

### 1. Cài đặt cấu hình project env

```http
POST /project-notebook-configs
Content-Type: application/json
```

```json
{
  "project_name": "projectA",
  "notebook_env": "env_a",
  "notebook_id": "nb-123",
  "notebooklm_auth_name": "team-a.json"
}
```

Hoặc dùng script local:

```bash
python3 scripts/import_project_config.py projectA env_a nb-123 team-a.json
```

### 2. Ingest spreadsheet

Request:

```json
{
  "project_name": "projectA",
  "notebook_env": "env_a",
  "spreadsheet_id": "<Google-Sheet-file-ID>",
  "output_name": "requirements.md"
}
```

`output_name` chỉ được là tên file Markdown đơn giản, không chứa path hoặc thư
mục con.

Response thành công gồm:

```json
{
  "project_name": "projectA",
  "notebook_env": "env_a",
  "spreadsheet_id": "<Google-Sheet-file-ID>",
  "notebook_id": "<notebook-id>",
  "source_id": "<source-id>",
  "artifact_id": "<artifact-id>",
  "output_md": "/app/project_data/docs/imported/projectA/requirements.md"
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
    "project_name": "projectA",
    "notebook_env": "env_a",
    "spreadsheet_id": "<Google-Sheet-file-ID>",
    "output_name": "test-spreadsheet.md"
  }'
```

Hoặc gọi bằng CLI script:

```bash
python3 scripts/ingest_spreadsheet.py \
  projectA env_a \
  "https://docs.google.com/spreadsheets/d/<ID>/edit" \
  sales-report.md
```

Kết quả nằm trong `docs/imported/projectA/test-spreadsheet.md`. Metadata của lần
xử lý nằm trong `docs/imported/projectA/.manifest.json`.

## Xử lý lỗi report generation

NotebookLM generation là thao tác bất đồng bộ. Một số phiên bản CLI trả về
`task_id` thay vì `artifact_id` sau lệnh `generate report`. Adapter trong
`services/knowledge_service/notebooklm_service.py` hỗ trợ cả hai dạng, sau đó
luôn gọi `artifact wait` trước khi tải report.

Lỗi phổ biến:

- `Config not found for project_name=... and notebook_env=...`: chưa cài đặt cấu hình trong MongoDB.
- `NotebookLM auth file '...' was not found in auth directory`: thiếu file auth JSON trong `NOTEBOOKLM_AUTH_DIR`.
- Lỗi xác thực `401`/`403`: session Google hết hạn, cần tạo lại file auth JSON thủ công.
- Lỗi quyền Spreadsheet: tài khoản trong NotebookLM session không có quyền đọc
  Spreadsheet.
- Report chưa hoàn tất: kiểm tra log service và trạng thái artifact trong
  notebook.

## Các file liên quan

- `services/knowledge_service/notebooklm_service.py`: adapter gọi NotebookLM.
- `services/knowledge_service/main.py`: endpoint `/ingest-spreadsheet` và CRUD config.
- `services/knowledge_service/project_config_store.py`: repository MongoDB cho config.
- `services/knowledge_service/manifest.py`: lưu metadata xử lý.

## Xóa dữ liệu MongoDB

Kiểm tra trước khi xóa:

```bash
python3 scripts/clear_knowledge_database.py --dry-run
```

Xóa toàn bộ MongoDB database `knowledge_service`:

```bash
python3 scripts/clear_knowledge_database.py --yes
```

Có thể truyền URI và database khác bằng `--mongodb-uri` và `--database`. Thao tác này
không xóa collection trên Qdrant, file Markdown, manifest hoặc auth JSON.
- `services/knowledge_service/tests/test_notebooklm_service.py`: unit test
  adapter với response `artifact_id` và `task_id`.
- `services/knowledge_service/tests/test_project_config_store.py`: unit test repository config.
- `docker-compose.yml`: khởi động MongoDB và truyền cấu hình vào container.

## Giới hạn hiện tại

- Manifest đang quản lý theo `project_name`, chưa tách riêng theo `notebook_env`.
- Auth file do người vận hành tạo thủ công; service chỉ validate tên file và sự tồn tại file.
- `notebooklm-py` là thư viện không chính thức và phụ thuộc API nội bộ của NotebookLM.
- Việc tạo report vẫn là synchronous; request có thể mất thời gian với Spreadsheet lớn.
