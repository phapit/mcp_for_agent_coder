# Knowledge Ingestion — Đồng bộ Qdrant, Registry, Health & Bảo mật

Tài liệu này mô tả pipeline ingest của `knowledge_service` sau đợt nâng cấp 2026-07 (đồng bộ an toàn với Qdrant, document registry, retry/dead-letter, background worker, metadata filter, health check và các lớp bảo mật).

## 1. Đồng bộ ingest với Qdrant

`POST /ingest` quét `DOCS_GLOB` (mặc định `/app/project_data/docs/imported/**/*.md`) và đồng bộ từng file với collection `project_docs`:

- **Point ID định danh**: sinh từ `sha256(document_id : chunk_index : chunk_text)` chuyển thành UUID — cùng nội dung luôn cho cùng ID, không còn đánh số từ 0.
- **`document_id`**: `sha256` của đường dẫn nguồn đã chuẩn hóa (xem `document_identity.py`).
- **Skip theo `content_hash`**: file không đổi nội dung sẽ bị bỏ qua.
- **Thay thế theo tài liệu**: khi nội dung đổi, chunk mới được upsert rồi chunk của phiên bản cũ (khác `content_hash`) bị xóa — không tồn tại đồng thời dữ liệu cũ và mới.
- **Prune**: file đã xóa khỏi ổ đĩa ⇒ vector tương ứng bị xóa khỏi Qdrant (bao gồm cả point kiểu cũ không có `document_id`).

### Payload của mỗi point

| Field | Ý nghĩa |
|---|---|
| `text`, `source`, `chunk_index` | Nội dung chunk và vị trí |
| `document_id` | Định danh ổn định của tài liệu |
| `content_hash` | sha256 nội dung file tại thời điểm ingest |
| `version` | Tăng 1 mỗi lần nội dung thay đổi |
| `ingested_at` | Timestamp UTC ISO-8601 |
| `project` | Thư mục con đầu tiên dưới docs root (vd. `ss_pocket`) |
| `environment` | Biến môi trường `ENVIRONMENT` (mặc định `local`) |
| `document_type` | Đuôi file (vd. `md`) |

Tất cả field trên (trừ `text`) đều có payload index trong Qdrant.

### Request body

```json
{ "force": false, "prune": true, "background": false }
```

- `force`: ingest lại kể cả khi hash không đổi; đồng thời bỏ qua trạng thái dead-letter.
- `prune`: xóa vector của file không còn tồn tại (mặc định bật).
- `background`: trả về `202` ngay và chạy trong worker thread; theo dõi qua `GET /ingest/status`. Khi có run đang chạy, request mới trả `409`.

## 2. Document registry (MongoDB)

Collection `document_registry` (đổi qua `MONGODB_REGISTRY_COLLECTION`) lưu trạng thái từng tài liệu: `source`, `content_hash`, `version`, `chunks`, `status`, `attempts`, `error`, `metadata`, `ingested_at`.

Trạng thái: `ingested` → (`failed` → … → `dead_letter`) / `removed`.

- File lỗi được retry ở các lần ingest sau; sau `MAX_INGEST_ATTEMPTS` lần (mặc định 3) chuyển `dead_letter` và bị bỏ qua.
- Attempts đếm **theo content_hash**: file dead-letter được sửa nội dung sẽ tự động được thử lại từ đầu.

### Endpoint liên quan

| Endpoint | Chức năng |
|---|---|
| `GET /ingest/status` | Kết quả lần ingest gần nhất (running / completed / failed, chi tiết từng file) |
| `GET /ingest/documents?status=` | Liệt kê registry theo trạng thái |
| `GET /ingest/dead-letter` | Danh sách tài liệu dead-letter |
| `POST /ingest/dead-letter/requeue?document_id=` | Đưa dead-letter (một hoặc tất cả) về hàng đợi retry |

## 3. Search / Answer với metadata filter

`POST /search` và `POST /answer` nhận thêm `filters` (AND các điều kiện):

```json
{
  "query": "authentication flow",
  "limit": 5,
  "filters": { "project": "ss_pocket", "environment": "local", "document_type": "md", "version": 2 }
}
```

Lưu ý: point ingest trước đợt nâng cấp không có metadata nên không khớp filter — chạy `POST /ingest {"force": true}` một lần để gắn metadata cho toàn bộ dữ liệu (đã thực hiện ngày 2026-07-16).

## 4. Health check

Cả `knowledge_service` và `agent_service`:

- `GET /health/live`: process còn sống (`/health` cũ là alias, giữ tương thích).
- `GET /health/ready`: trả `503` kèm chi tiết `checks` khi dependency lỗi.
  - knowledge_service kiểm tra: Qdrant, MongoDB, embedding model, Ollama, OpenAI (ready khi có ít nhất một AI provider).
  - agent_service kiểm tra: git repo, knowledge_service.

docker-compose có `healthcheck` gọi `/health/ready` cho cả hai container.

## 5. Bảo mật

| Cơ chế | Chi tiết | Biến môi trường |
|---|---|---|
| API key bắt buộc | Service **từ chối khởi động** khi `SERVICE_API_KEY` rỗng; mọi endpoint (trừ health) yêu cầu header `X-API-Key` | `SERVICE_API_KEY` |
| Rate limit | Theo IP, mặc định 120 request/phút, trả `429` + `Retry-After`; health được miễn | `RATE_LIMIT_PER_MINUTE` |
| Giới hạn upload | Chặn theo `Content-Length` và kích thước thực tế, trả `413`; mặc định 20 MB | `MAX_UPLOAD_SIZE_MB` |
| CORS | Chỉ bật khi khai báo danh sách origin (phân tách dấu phẩy); rỗng = tắt | `ALLOWED_ORIGINS` |
| Non-root container | Cả hai image chạy user `appuser` (uid 1000, khớp owner volume host) | — |

## 6. Chạy test

Host không có đủ dependency; chạy pytest trong image đã build:

```bash
docker run --rm -v $PWD/services/knowledge_service:/app -w /app -e HF_HUB_OFFLINE=1 \
  obsidian-wiki-knowledge_service:latest python -m pytest tests -q

docker run --rm -v $PWD/services/agent_service:/app -w /app \
  obsidian-wiki-agent_service:latest python -m pytest tests -q
```

## 7. Chất lượng tìm kiếm & trả lời (2026-07)

Nhóm tính năng khắc phục postmortem "semantic search lấy sai context".

### Hybrid search + rerank + ngưỡng điểm
- `/search` chạy song song **dense** (vector cosine) và **keyword** (full-text index của Qdrant trên field `text`, chấm BM25 cục bộ), trộn bằng **RRF**. Ứng viên chỉ có keyword phải đạt ≥ 50% điểm keyword cao nhất mới được giữ.
- **Rerank** (tùy chọn, `RERANK_ENABLED=1`): cross-encoder `RERANK_MODEL` chấm lại cặp (câu hỏi, chunk), điểm sigmoid 0–1.
- **Ngưỡng điểm**: `MIN_SCORE_THRESHOLD` (cosine, mặc định 0.35) hoặc `MIN_RERANK_SCORE` (mặc định 0.3) khi rerank bật. `/answer` trả 404 thay vì trả lời từ context không đạt ngưỡng.
- Env: `HYBRID_SEARCH_ENABLED`, `RERANK_ENABLED`, `RERANK_MODEL`, `MIN_SCORE_THRESHOLD`, `MIN_RERANK_SCORE`, `CANDIDATE_POOL_MULTIPLIER`, `RRF_K`.

### Citation chi tiết
- Chunking mới (`chunking.py`) giữ **heading path** và **số dòng** (`start_line`–`end_line`) trong payload Qdrant.
- `/search` và `/answer` trả về `heading`, `start_line`, `end_line`; `/answer` có mảng `citations` (mỗi phần tử: `context_id`, `source`, `heading`, dòng, `score`).

### Chống prompt injection từ tài liệu (`guardrails.py`)
- Chunk được sanitize trước khi vào prompt: gỡ ký tự ẩn/zero-width, HTML comment, mẫu "ignore previous instructions", giả vai `system:`… và thay bằng dấu vô hiệu hóa.
- Prompt v2 bọc từng chunk trong fence `<<<context-N>>>` và chỉ thị model coi context là dữ liệu, không phải mệnh lệnh.

### Prompt versioning (`prompts.py`)
- `PROMPT_VERSION` (env, mặc định `v2`); client có thể override bằng `prompt_version` trong body `/answer`. Response luôn trả `prompt_version` đã dùng. Thêm version mới thay vì sửa version cũ.

### Conversation/session context (`session_store.py`)
- Gửi `session_id` trong `/answer` để bật hội thoại nhiều lượt; các lượt trước (tối đa `SESSION_CONTEXT_TURNS`, mặc định 5) được chèn vào messages. Lưu MongoDB collection `chat_sessions` (cap `SESSION_MAX_TURNS`).
- `GET /sessions/{id}` xem lịch sử, `DELETE /sessions/{id}` xóa.

### Auto-ingest sau export
- Sau khi `/ingest-excel`, `/ingest-excel/upload`, `/ingest-spreadsheet` xuất Markdown thành công, service tự chạy ingest nền (`AUTO_INGEST_AFTER_EXPORT=1`, mặc định bật). Response có field `auto_ingest` cho biết trạng thái (`started` / `already_running` / `disabled`…).

### Trạng thái & lịch sử ingest
- `GET /ingest/status`: lần chạy gần nhất (như cũ).
- `GET /ingest/history?limit=20`: lịch sử bền trong MongoDB (`ingest_runs`), mỗi record có `run_id`, `trigger` (manual/excel_export/notebooklm_export…), số lượng ingested/skipped/failed và chi tiết lỗi.

### Đánh giá chất lượng RAG
- Bộ câu hỏi chuẩn: `eval/golden_questions.json` (có cả câu ngoài phạm vi để đo khả năng từ chối).
- Chạy: `KNOWLEDGE_URL=http://localhost:8002 SERVICE_API_KEY=... python scripts/rag_eval.py` → in `retrieval_hit_rate`, `answer_pass_rate`, `refusal_rate`; exit code ≠ 0 nếu có câu fail. Dùng `--skip-answer` nếu chỉ đo retrieval.
