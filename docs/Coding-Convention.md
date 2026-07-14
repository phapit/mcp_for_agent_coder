# Quy tắc lập trình (Coding Convention)

Áp dụng cho toàn bộ code Python trong `services/*` của dự án.

## Chuẩn ngôn ngữ

- Python 3.11, tuân thủ PEP 8.
- Dùng type hint + Pydantic `BaseModel` cho mọi request/response body của FastAPI
  (xem `SearchQuery`, `AnswerQuery`, `BranchName` trong `services/*/main.py` làm ví dụ).
- Validate input bằng Pydantic (`Field(..., pattern=...)`) thay vì kiểm tra thủ công trong hàm.

## Cấu trúc thư mục dịch vụ

Mỗi service là một microservice độc lập, đặt trong `services/<tên_service>/`, gồm:
```
services/<tên_service>/
├── main.py           # FastAPI app, endpoint cho service này
├── requirements.txt  # dependency riêng của service (không dùng chung 1 file requirements ở root)
└── Dockerfile        # build image riêng
```
Không đặt logic của nhiều service vào cùng 1 `main.py` — mỗi service chỉ đảm nhiệm đúng phạm vi
đã mô tả trong `docs/Architecture.md` (Knowledge Curator vs. AI Developer).

## Cấu hình qua biến môi trường

Mọi giá trị có thể thay đổi giữa môi trường (host, port, tên model, API key...) phải đọc qua
`os.getenv("TEN_BIEN", "gia_tri_mac_dinh")`, không hard-code. Ví dụ chuẩn trong
`services/knowledge_service/main.py`:
```python
QDRANT_HOST = os.getenv("QDRANT_HOST", "qdrant")
QDRANT_PORT = int(os.getenv("QDRANT_PORT", 6333))
```

## Khởi tạo client/model toàn cục

Các client tốn chi phí khởi tạo (embedding model, Qdrant client, OpenAI client, Git repo) được
khởi tạo **một lần ở module scope**, bọc trong `try/except`. Nếu lỗi, gán về `None` và log lỗi —
không để service crash khi khởi động, thay vào đó trả `HTTPException(503)` ở từng endpoint khi
client cần dùng là `None`. Không khởi tạo lại các client này bên trong từng request.

## Logging

Dùng `logging` chuẩn của Python, cấu hình 1 lần ở đầu file:
```python
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
```
Log lỗi với `exc_info=True` khi bắt exception để giữ traceback.

## Xử lý lỗi API

- Lỗi do thiếu tài nguyên/config (client chưa sẵn sàng, thiếu API key) → `HTTPException(503)`.
- Lỗi do input người dùng không hợp lệ hoặc trùng lặp (VD: branch đã tồn tại) → `HTTPException(400)`.
- Lỗi không tìm thấy dữ liệu (VD: không có file để ingest, không có kết quả tìm kiếm) → `HTTPException(404)`.
- Lỗi hệ thống ngoài tầm kiểm soát (Git command lỗi, dịch vụ phụ thuộc không phản hồi) → `HTTPException(500)`
  hoặc `503` tùy theo có thể phục hồi hay không, kèm log `exc_info=True`.

## Giao tiếp giữa các service

Service gọi service khác qua HTTP nội bộ trong network `ai_agent_net` (Docker Compose), dùng
`httpx.AsyncClient`, luôn set `timeout` tường minh và bắt riêng `httpx.HTTPStatusError` /
`httpx.RequestError` để trả lỗi rõ ràng thay vì để exception chung chung lan ra ngoài
(xem `/consult` trong `services/agent_service/main.py`).

## Nguyên tắc chung (từ `docs/AGENT-Behavioral-Guidelines.md`)

1. Think Before Coding — làm rõ giả định trước khi viết code.
2. Simplicity First — chỉ giải quyết đúng vấn đề hiện tại.
3. Surgical Changes — sửa đúng phần cần sửa, giữ nguyên phong cách sẵn có.
4. Goal-Driven Execution — mỗi task có tiêu chí thành công kiểm chứng được (smoke test/unit test).
