# Architecture Handoff

## Bối cảnh

`docker-compose.yml` đã định nghĩa 2 service (`knowledge_service`, `agent_service`) build từ
`./services/knowledge_service` và `./services/agent_service`, đúng với mô tả trong `Architecture.md`.
Tuy nhiên trước phiên làm việc này, 2 thư mục đó không tồn tại — chỉ có 1 file `main.py` gộp chung
(git ops + stub cho search/answer) ở root. Đây là điểm sai lệch giữa tài liệu kiến trúc và mã nguồn.

## Phương án đã xem xét

1. **Gộp thành 1 service duy nhất** — sửa `docker-compose.yml` để khớp với `main.py` hiện có.
   Ít công sức hơn, nhưng đi ngược lại `Architecture.md` và làm mất ranh giới rõ ràng giữa
   "Knowledge Curator" và "AI Developer" mà tài liệu mô tả.
2. **Tách thành 2 microservice đúng theo `Architecture.md`** (đã chọn) — mỗi service có
   Dockerfile/requirements riêng, giao tiếp qua HTTP nội bộ trong `ai_agent_net`.

## Quyết định

Chọn phương án 2. Lý do: giữ đúng ranh giới trách nhiệm đã được tài liệu hóa, cho phép scale/deploy
độc lập từng service, và không cần sửa `docker-compose.yml` (đã đúng sẵn).

## Thiết kế

- **`services/knowledge_service`** (port 8000)
  - `POST /ingest`: đọc toàn bộ `docs/**/*.md` (qua volume `.:/app/project_data`), chia nhỏ bằng
    `MarkdownTextSplitter`, tạo embedding (`sentence-transformers/all-MiniLM-L6-v2`), upsert vào Qdrant.
  - `POST /search`: embed câu hỏi, tìm kiếm ngữ nghĩa trong Qdrant, trả về các đoạn liên quan.
  - `POST /answer`: gọi `/search` lấy ngữ cảnh, sau đó gọi OpenAI Chat Completion để trả lời có trích dẫn nguồn.
- **`services/agent_service`** (port 8001)
  - `GET /git/status`, `POST /git/branch`: thao tác Git trên repo mount tại `/app/project_data` (giữ nguyên từ code cũ).
  - `POST /consult`: proxy câu hỏi sang `knowledge_service:8000/answer` qua HTTP nội bộ, để agent tra cứu
    tài liệu chuẩn hóa trước khi phân tích/sinh mã.

## File đã xóa

- `main.py`, `Dockerfile`, `requirements.txt` ở root — logic đã được chuyển vào 2 service tương ứng,
  không còn được `docker-compose.yml` tham chiếu tới nên là dead code.

## Việc còn lại / cần Pháp xác nhận

- Cần cấu hình `OPENAI_API_KEY` (biến môi trường) để `/answer` hoạt động; hiện chưa có cơ chế truyền secret
  (nên dùng `.env` + `env_file` trong `docker-compose.yml`, chưa triển khai trong phiên này).
- Chưa chạy `docker compose up` thực tế trong sandbox này (không có Docker/mạng ra ngoài để kiểm thử build
  và tải model embedding) — cần Pháp hoặc CI chạy smoke test thực tế theo Giai đoạn 3 của `AGENTS.md`.
- `docs/Database-Design.md`, `Business-Rules.md`, `Coding-Convention.md`, `Postmortems.md` vẫn là placeholder rỗng.

## 2026-07-15 Ổn định hóa NotebookLM theo project/env

### Phương án đã xem xét

1. Giữ client truyền trực tiếp `notebook_id` và `notebooklm_auth_name` trong mỗi request `/ingest-spreadsheet`.
   Triển khai nhanh hơn nhưng khiến client phải biết chi tiết hạ tầng NotebookLM, khó đổi cấu hình theo môi trường.
2. Lưu cấu hình `project_name + notebook_env` vào MongoDB rồi để service tự resolve `notebook_id` và
   `notebooklm_auth_name` khi ingest. Đây là phương án đã chọn.

### Quyết định

Chọn phương án 2 vì:

- Client gọi API đơn giản hơn, chỉ cần `project_name` và `notebook_env`.
- Một project có thể quản lý nhiều môi trường NotebookLM độc lập mà không phải sửa client.
- Auth JSON vẫn được quản lý thủ công bằng file local, không nhét raw secret vào request.

### Thiết kế

- Thêm service `mongodb` trong `docker-compose.yml`.
- `knowledge_service` dùng collection `project_notebook_configs` trong MongoDB để lưu:
  - `project_name`
  - `notebook_env`
  - `notebook_id`
  - `notebooklm_auth_name`
  - `created_at`
  - `updated_at`
- Tạo nhóm API CRUD:
  - `POST /project-notebook-configs`
  - `GET /project-notebook-configs/{project_name}`
  - `GET /project-notebook-configs/{project_name}/{notebook_env}`
  - `PUT /project-notebook-configs/{project_name}/{notebook_env}`
  - `DELETE /project-notebook-configs/{project_name}/{notebook_env}`
- Sửa `POST /ingest-spreadsheet`:
  - Input chỉ còn `project_name`, `notebook_env`, `spreadsheet_url`, `output_name`
  - Resolve config từ MongoDB
  - Đọc auth file từ `NOTEBOOKLM_AUTH_DIR/<notebooklm_auth_name>`
  - Lưu Markdown vào `docs/imported/<project_name>/`
  - Ghi metadata `project_name`, `notebook_env`, `notebook_id`, `notebooklm_auth_name` vào manifest của project

### Trade-off

- Chưa tách manifest theo `notebook_env`; hiện tại manifest gom theo `project_name` đúng với phương án 1 đã chốt.
- Auth file chỉ được validate theo tên file và `.json`; chưa kiểm tra schema JSON ở bước cấu hình, chỉ lỗi khi NotebookLM CLI dùng thực tế.
