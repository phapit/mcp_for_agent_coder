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
  "output_name": "requirements.md",
  "language": "vi"
}
```

`output_name` chỉ được là tên file Markdown đơn giản, không chứa path hoặc thư
mục con.

`language` (tùy chọn) là mã ngôn ngữ đầu ra cho bước generate report, truyền
per-command qua cờ `--language` của NotebookLM CLI (vd: `vi`, `en`, `ja`,
`zh_Hans`, `ko`, `fr`). Bỏ trống để dùng mặc định của NotebookLM
(`NOTEBOOKLM_HL` env → config global → `en`).

**Lưu ý quan trọng:** `--language` chỉ tác động khi **tạo report mới**. Nếu
report cho spreadsheet này đã tồn tại, luồng tái sử dụng report cũ và **bỏ qua
`language`** (response trả `report_reused: true`). Muốn ép tạo lại bằng ngôn
ngữ khác, đổi `output_name` để không khớp report cũ.

Response thành công gồm:

```json
{
  "project_name": "projectA",
  "notebook_env": "env_a",
  "spreadsheet_id": "<Google-Sheet-file-ID>",
  "notebook_id": "<notebook-id>",
  "source_id": "<source-id>",
  "artifact_id": "<artifact-id>",
  "output_md": "/app/project_data/docs/imported/projectA/requirements.md",
  "language": "vi",
  "report_reused": false
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

## Xuất tài liệu theo yêu cầu tự do (custom report)

`POST /notebook-reports` cho phép nhập một **prompt tự do** để NotebookLM tạo
tài liệu theo đúng yêu cầu, dựa trên các source **đã có sẵn** trong notebook
của dự án (không thêm source mới — cần chạy `/ingest-spreadsheet` hoặc thêm
source thủ công trước). Ví dụ: "Mô tả chi tiết logic hoạt động của button A".

```http
POST /notebook-reports
Content-Type: application/json
```

```json
{
  "project_name": "projectA",
  "notebook_env": "env_a",
  "prompt": "Mô tả chi tiết logic hoạt động của button A",
  "output_name": "button-a.md",
  "format": "custom",
  "language": "vi"
}
```

Field:

| Field | Bắt buộc | Mô tả |
|---|---|---|
| `prompt` | có | Yêu cầu tự do, truyền thẳng vào `generate report [prompt]` của NotebookLM CLI. Tối đa **1024 ký tự** (422 nếu vượt). |
| `output_name` | không (mặc định `custom-report.md`) | Tên file `.md` đơn giản, không chứa path. |
| `format` | không (mặc định `custom`) | `briefing-doc` \| `study-guide` \| `blog-post` \| `custom`. Với `custom`, prompt là toàn quyền chỉ dẫn nội dung; các định dạng còn lại dùng template có sẵn của NotebookLM, prompt chỉ override phần mô tả mở đầu. |
| `append` | không | Chỉ có tác dụng khi `format != custom` — thêm chỉ dẫn bổ sung vào template có sẵn. |
| `language` | không | Mã ngôn ngữ đầu ra (per-command `--language`, vd `vi`, `en`, `ja`). Bỏ trống dùng mặc định NotebookLM. |

Khác với `/ingest-spreadsheet`, endpoint này **luôn generate report mới** —
không tái sử dụng report cũ, vì mỗi prompt có thể cho ra nội dung khác nhau.
Response trả `artifact_id`, `output_md`, `format`, `language` và kích hoạt
`auto_ingest` giống các endpoint export khác.

```bash
curl -X POST http://localhost:8002/notebook-reports \
  -H "Content-Type: application/json" -H "X-API-Key: $SERVICE_API_KEY" \
  -d '{
    "project_name": "projectA",
    "notebook_env": "env_a",
    "prompt": "Mô tả chi tiết logic hoạt động của button A",
    "output_name": "button-a.md"
  }'
```

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

## Resume source/artifact và xử lý rate limit

Luồng `POST /ingest-spreadsheet` kiểm tra dữ liệu NotebookLM trước khi tạo mới:

1. Gọi `source list --json` và tái sử dụng source đã tồn tại theo Spreadsheet ID.
2. Gọi `artifact list --type report --json` và tái sử dụng report phù hợp theo Spreadsheet ID hoặc tên output.
3. Chỉ gọi `source add-drive` hoặc `generate report` khi chưa tìm thấy dữ liệu phù hợp.
4. Dùng `artifact wait` trước khi download report.
5. Nếu NotebookLM trả `RateLimitError`, API trả HTTP `429`; client không tạo lại source/artifact ngay lập tức.
6. Gọi lại request sau đó sẽ kiểm tra lại source/artifact và tiếp tục download artifact đã được tạo trước đó.

Các lệnh CLI được sử dụng dựa trên `docs/notebooklm-py/notebooklm-cli-reference.md`:

- `source list --json`
- `artifact list --type report --json`
- `source wait`
- `artifact wait`
- `download report --artifact`

Flow hiện tại resume bằng source/artifact ID của NotebookLM ở lần gọi kế tiếp; API polling `job_id` độc lập sẽ được bổ sung khi pipeline background worker/Kafka hoàn tất.
- `services/knowledge_service/tests/test_notebooklm_service.py`: unit test
  adapter với response `artifact_id` và `task_id`.
- `services/knowledge_service/tests/test_project_config_store.py`: unit test repository config.
- `docker-compose.yml`: khởi động MongoDB và truyền cấu hình vào container.

## Vận hành: distributed lock/throttle qua Redis

Tài khoản Google NotebookLM cá nhân dùng chung giữa công việc hàng ngày (thao
tác thủ công trên web) và service này (AI coder agent gọi qua CLI). Gọi API
quá nhanh/quá dồn dập có thể khiến Google flag tài khoản. `notebooklm_lock.py`
chèn một lớp distributed lock/throttle qua Redis trước khi
`NotebookLMService` (trong `notebooklm_service.py`) chạy lệnh CLI, áp dụng cho
cả `/ingest-spreadsheet` và `/notebook-reports`.

### Cơ chế

1. **Lock độc quyền theo `notebook_id`** — mỗi notebook chỉ cho 1 request xử
   lý tại một thời điểm (Redis lock `notebooklm:lock:<notebook_id>`). Request
   tới **notebook khác** vẫn chạy song song bình thường, không bị chặn chéo.
2. **Khoảng nghỉ ngẫu nhiên giữa 2 lần gọi liên tiếp cùng notebook** — sau khi
   giành được lock, service đọc thời điểm gọi trước đó
   (`notebooklm:last_call:<notebook_id>`) và ngủ thêm nếu chưa đủ khoảng nghỉ
   ngẫu nhiên (mặc định 2–4s), tránh gọi CLI dồn dập ngay cả khi các request
   xếp hàng liên tục.
3. Khi thân request chạy xong (thành công hay lỗi), service ghi lại thời điểm
   gọi rồi mới release lock.

### Biến môi trường (`.env`, xem `.env.example`)

| Biến | Ý nghĩa | Mặc định |
|---|---|---|
| `REDIS_URL` | Kết nối tới Redis dùng cho lock | `redis://redis:6379/0` |
| `NOTEBOOKLM_LOCK_LEASE_S` | Lease tối đa một lock được giữ trước khi bị coi là "mồ côi" (process crash không release) và có thể bị cướp | `600` |
| `NOTEBOOKLM_LOCK_WAIT_TIMEOUT_S` | Thời gian tối đa 1 request chờ để giành lock của notebook đang bận trước khi trả lỗi | `600` |
| `NOTEBOOKLM_THROTTLE_MIN_DELAY_S` / `NOTEBOOKLM_THROTTLE_MAX_DELAY_S` | Khoảng nghỉ ngẫu nhiên (giây) giữa 2 lần gọi liên tiếp tới cùng notebook | `2` / `4` |

Container Redis (`notebooklm_redis` trong `docker-compose.yml`) chỉ dùng làm
lock ephemeral: không bật persistence (`--save ""`, `--appendonly no`), không
expose port ra ngoài `ai_agent_net`.

### Lỗi và HTTP status

- **429** (`NotebookLMLockTimeoutError`): notebook đang bị request khác giữ
  quá lâu (vượt `NOTEBOOKLM_LOCK_WAIT_TIMEOUT_S`). Retry sau, không phải lỗi
  dữ liệu.
- **503** (`NotebookLMLockError`): không kết nối được Redis. Kiểm tra
  container `notebooklm_redis` và `REDIS_URL`.
- **503** (do `notebooklm_lock_manager is None`): service khởi động Redis
  thất bại lúc startup (xem log `main.py`); route trả lỗi ngay, không thử gọi
  NotebookLM CLI.

### Kiểm tra sức khỏe

```bash
curl http://localhost:8002/health/ready
```

Field `redis` trong response: `ok` / `not_initialized` / `error: ...`.

### File liên quan

- `services/knowledge_service/notebooklm_lock.py`: `NotebookLMLockManager`,
  context manager `throttle(notebook_id)`.
- `services/knowledge_service/notebooklm_service.py`: gọi `lock_manager.throttle()`
  bao quanh các lệnh CLI.
- `services/knowledge_service/routes_notebooklm.py`: map lỗi lock sang HTTP 429/503.
- `services/knowledge_service/main.py`: khởi tạo `redis_client` / `notebooklm_lock_manager`, health check `redis`.

## Giới hạn hiện tại

- Manifest đang quản lý theo `project_name`, chưa tách riêng theo `notebook_env`.
- Auth file do người vận hành tạo thủ công; service chỉ validate tên file và sự tồn tại file.
- `notebooklm-py` là thư viện không chính thức và phụ thuộc API nội bộ của NotebookLM.
- Việc tạo report vẫn là synchronous; request có thể mất thời gian với Spreadsheet lớn.
