## Kiến trúc hệ thống & Vai trò của từng thành phần
# Obsidian

Đóng vai trò:

- Project Wiki
- Architecture Document
- Coding Convention
- Business Rule
- Database Design
- Incident History
- Postmortem

# notebooklm-py

NotebookLM rất mạnh ở việc:

- Tóm tắt tài liệu
- Truy vấn tài liệu
- Tạo knowledge graph
- Trả lời câu hỏi từ tài liệu

# AI Agent (Codex, Claude, Gravity,...):

"AI Senior Developer" có thể tự đọc tài liệu dự án, tự phân tích bug, tự tạo PR và dần hiểu hệ thống tốt hơn theo thời gian, tôi có thể đề xuất một kiến trúc hoàn chỉnh sử dụng Codex + Obsidian + Qdrant + MCP + GitHub Actions theo hướng gần giống các hệ thống AI engineering agent hiện đại đang được nhiều công ty áp dụng.
```

                   ┌─────────────┐
                   │  Obsidian   │
                   │ Project Wiki│
                   └──────┬──────┘
                          │
                          ▼
                  ┌───────────────┐
                  │ Knowledge     │
                  │ Curator       │
                  │ (NotebookLM)  │
                  └──────┬────────┘
                         │
                         ▼
                ┌───────────────────┐
                │ Markdown Knowledge│
                │ Canonical Docs    │
                └─────────┬─────────┘
                          │
                          ▼
                  ┌──────────────┐
                  │ Embeddings   │
                  └──────┬───────┘
                         │
                         ▼
                  ┌──────────────┐
                  │ Qdrant       │
                  │ Vector Store │
                  └──────┬───────┘
                         │
        ┌────────────────┴───────────────┐
        │                                │
        ▼                                ▼
┌─────────────────┐           ┌─────────────────┐
│ Code Analyzer   │           │ AI Developer    │
│ Tree-Sitter     │           │ Codex/Claude,.. │
└─────────────────┘           └─────────────────┘
        │                                │
        └──────────────┬─────────────────┘
                       ▼
                Git Repository
```

## Setup / Vận hành

### Ingest tài liệu vào Qdrant

`POST /ingest` đồng bộ Markdown trong `docs/imported/` với Qdrant: point ID định danh theo tài liệu,
skip theo `content_hash`, tự xóa vector của file đã xóa, registry trạng thái trong MongoDB với
retry/dead-letter, hỗ trợ chạy background và search có metadata filter
(`project` / `environment` / `document_type` / `version`).

Chi tiết endpoint, payload và cấu hình: xem [docs/Knowledge-Ingestion.md](docs/Knowledge-Ingestion.md).

```bash
# Ingest toàn bộ (chạy nền, theo dõi qua /ingest/status)
curl -X POST http://localhost:8002/ingest \
  -H "X-API-Key: $SERVICE_API_KEY" -H "Content-Type: application/json" \
  -d '{"force": false, "background": true}'
```

Health check: `/health/live` (process sống) và `/health/ready` (kiểm tra Qdrant, MongoDB,
embedding model, AI provider — trả 503 khi dependency lỗi).

Bảo mật: service không khởi động nếu thiếu `SERVICE_API_KEY`; rate limit theo IP
(`RATE_LIMIT_PER_MINUTE`, mặc định 120/phút); giới hạn upload (`MAX_UPLOAD_SIZE_MB`, mặc định 20 MB);
CORS chỉ bật khi khai báo `ALLOWED_ORIGINS`; container chạy non-root (uid 1000).

### Cấu hình API key cho script CLI

Các script gọi API không lưu API key trong source. Cần cấu hình biến môi trường trước khi chạy:

```bash
export SERVICE_API_KEY="your-service-api-key"
```

Biến này được gửi qua header `X-API-Key` bởi `import_project_config.py` và
`ingest_spreadsheet.py`. Nếu chưa cấu hình, script sẽ dừng với lỗi rõ ràng.

### Khởi động hệ thống
```
docker compose up -d --build
```

### Import cấu hình project NotebookLM

Sau khi `knowledge_service` đã chạy, có thể import nhanh cấu hình cho từng project/env:

```bash
python3 scripts/import_project_config.py projectA env_a nb-123 team-a.json
```

Nếu API không chạy ở `http://localhost:8000`, truyền thêm `--base-url`:

```bash
python3 scripts/import_project_config.py projectA env_a nb-123 team-a.json --base-url http://127.0.0.1:8000
```

Gọi API ingest spreadsheet:

```bash
python3 scripts/ingest_spreadsheet.py \
  projectA env_a \
  "https://docs.google.com/spreadsheets/d/<ID>/edit" \
  sales-report.md
```

Có thể chỉ định URL service khác bằng `--base-url`.

Xóa toàn bộ dữ liệu trong MongoDB database `knowledge_service`:

```bash
python3 scripts/clear_knowledge_database.py --dry-run
python3 scripts/clear_knowledge_database.py --yes
```

Script chỉ xóa MongoDB database; không xóa dữ liệu Qdrant hoặc Markdown trong `docs/imported/`.

### Pull model cho Ollama (chạy 1 lần sau khi container `ollama` đã chạy)
`knowledge_service` hỗ trợ cả OpenAI (`gpt-4o-mini`, online) và Ollama (local, mặc định `llama3.2:3b`) cho endpoint `/answer` (chọn qua tham số `use_online_model`: `0` = Ollama, `1` = OpenAI). Trước khi dùng nhánh Ollama, cần pull model về:

```
docker exec -it ollama ollama pull llama3.2:3b
```

Đổi model bằng cách set biến môi trường `OLLAMA_MODEL` trước khi `docker compose up` (ví dụ `qwen2.5:7b`), rồi pull đúng model đó.
