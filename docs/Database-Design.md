# Thiết kế Cơ sở dữ liệu (Database Design)

Hệ thống không dùng RDBMS truyền thống. Toàn bộ dữ liệu tri thức được lưu dưới dạng vector embedding
trong **Qdrant** (vector store), được `knowledge_service` quản lý.

## Collection: `project_docs`

| Thuộc tính        | Giá trị mặc định                          | Ghi chú |
|-------------------|--------------------------------------------|---------|
| Tên collection    | `project_docs` (`COLLECTION_NAME`)         | Có thể override qua biến môi trường |
| Kích thước vector | 384                                        | Khớp với model embedding `all-MiniLM-L6-v2` (`EMBEDDING_MODEL`) |
| Distance metric   | `COSINE`                                   | Định nghĩa tại `_ensure_collection()` trong `services/knowledge_service/main.py` |

Collection được tạo tự động (nếu chưa tồn tại) khi gọi `POST /ingest` lần đầu, dựa trên kích thước
vector thực tế trả về từ model embedding — không cần migration thủ công.

## Cấu trúc 1 Point (bản ghi)

```json
{
  "id": 0,
  "vector": [0.123, -0.045, ...],
  "payload": {
    "text": "Nội dung đoạn văn bản (chunk) được trích từ file Markdown",
    "source": "/app/project_data/docs/Architecture.md"
  }
}
```

- `id`: số nguyên tăng dần, được cấp lại từ 0 mỗi lần chạy `/ingest` (không phải ID bền vững —
  chạy lại `/ingest` sẽ ghi đè toàn bộ theo ID trùng, không xóa point cũ có ID khác nếu số lượng chunk giảm).
- `text`: một chunk văn bản, được `MarkdownTextSplitter` chia từ file gốc (`CHUNK_SIZE=1000`,
  `CHUNK_OVERLAP=100`, có thể override qua biến môi trường).
- `source`: đường dẫn tuyệt đối tới file Markdown gốc (theo `DOCS_GLOB`, mặc định
  `/app/project_data/docs/**/*.md`), dùng để trích dẫn nguồn khi trả lời (`/answer`).

## Nguồn dữ liệu đầu vào

Toàn bộ file `*.md` trong `docs/` (mount qua volume `.:/app/project_data` trong `docker-compose.yml`)
là nguồn duy nhất được ingest. Khi PM/Tech Lead cập nhật tài liệu dự án, cần gọi lại `POST /ingest`
để đồng bộ tri thức trong Qdrant — hệ thống không tự động theo dõi thay đổi file (không có watcher).

## Việc còn thiếu

- Chưa có cơ chế xóa point cũ khi 1 file bị xóa hoặc số chunk giảm (có thể để lại point "rác").
  Cần cân nhắc `recreate_collection` hoặc gắn `source` làm filter để xóa theo file trước khi ingest lại.
- Chưa có versioning/point theo hash nội dung để tránh ingest trùng lặp.
