# Thiết kế: Pipeline Excel → LLM → Markdown (thay thế NotebookLM)

## Bối cảnh & mục tiêu

Kiến trúc hiện tại (xem `Architecture.md`) dùng NotebookLM làm "Knowledge Curator" — tóm tắt tài
liệu Obsidian thành Markdown chuẩn hóa trước khi tạo embeddings. Tuy nhiên NotebookLM không có
public API để tự động hóa bước này, và không giải quyết được nhu cầu thực tế: khách hàng cung cấp
~100 file Excel (đặc tả, lịch sử thay đổi yêu cầu) có chứa **hình ảnh minh họa** mà một pipeline
text-only sẽ bỏ sót.

Mục tiêu: xây dựng pipeline tự chủ, không phụ thuộc NotebookLM, convert Excel → Markdown, xử lý cả
phần text và phần ảnh (qua vision LLM), rồi đưa vào luồng ingest → embedding → Qdrant đã có sẵn.

## Nguyên tắc thiết kế

**Dữ liệu nghiệp vụ (số liệu, ngày tháng, nội dung đặc tả) không được đi qua LLM ở dạng "sinh mới"**
— chỉ trích xuất deterministic bằng code. LLM chỉ được dùng ở 2 vai trò giới hạn:
1. Vision LLM: mô tả (caption) nội dung ảnh.
2. Text LLM: làm sạch/định dạng lại Markdown từ nội dung đã trích xuất — không được thêm, xóa,
   hay chỉnh sửa dữ kiện, không được thay đổi link/caption ảnh.

Nguyên tắc này giảm rủi ro LLM bịa hoặc đọc sai dữ liệu đặc tả quan trọng.

## Kiến trúc

Không tạo service mới — mở rộng `knowledge_service` hiện có (đúng vai trò "Knowledge Curator" theo
`Architecture.md`), tách logic ra các module riêng để `main.py` chỉ khai báo endpoint:

```
services/knowledge_service/
├── main.py              # + 2 endpoint mới: /ingest-excel, /ingest-excel/upload
├── excel_ingest.py       # extractor + assembler + orchestration
├── vision.py             # gọi vision LLM để caption ảnh
├── manifest.py           # hash-based skip logic
└── tests/
    ├── fixtures/sample.xlsx   # file mẫu: 1 sheet, 2 dòng, 1 ảnh nhúng
    ├── test_excel_ingest.py
    └── test_manifest.py
```

Thư mục mới ở root repo: `excel_sources/` — chứa 100 file Excel gốc do khách hàng cung cấp. Thêm
vào `.gitignore` vì đây là dữ liệu nội bộ/khách hàng, không commit vào git. Được mount vào container
qua volume `.:/app/project_data` đã có sẵn trong `docker-compose.yml` (không cần sửa compose cho
việc mount, chỉ cần thêm biến môi trường trỏ đường dẫn).

Output ghi vào `docs/imported/<ten_file>/<ten_file>.md` + `docs/imported/<ten_file>/images/*`. Vì
`DOCS_GLOB` hiện tại (`docs/**/*.md`) là đệ quy, endpoint `/ingest` có sẵn sẽ tự động nhặt các file
Markdown mới này khi được gọi lại — không cần sửa `knowledge_service` phần ingest/embedding.

## Data flow

```
file.xlsx (bytes)
  → [Extractor] openpyxl đọc cell values theo từng sheet
                + unzip xlsx, parse xl/drawings/*.xml để lấy ảnh nhúng + vị trí neo (sheet, row)
  → [Vision Captioner] mỗi ảnh → gọi GPT-4o hoặc Claude vision (VISION_PROVIDER)
                        kèm ngữ cảnh vài dòng lân cận → caption tiếng Việt 1-3 câu
  → [Assembler] ghép text sheet (deterministic) + ![caption](images/imgN.ext)
                chèn đúng vị trí neo → "markdown thô"
  → [Refiner LLM] Ollama/OpenAI (tái dùng cờ use_online_model có sẵn) — CHỈ làm sạch format,
                  không được sửa/xóa/bịa link ảnh hay dữ liệu
  → ghi docs/imported/<stem>/<stem>.md + docs/imported/<stem>/images/*
  → cập nhật manifest (sha256 hash) — CHỈ ghi SAU KHI toàn bộ pipeline của file đó thành công
```

## Components

| Module / hàm | Trách nhiệm |
|---|---|
| `excel_ingest.extract_workbook(path)` | Đọc cell values theo sheet (free-form, không giả định cấu trúc cố định) + trích ảnh nhúng kèm vị trí neo (row gần nhất) |
| `vision.caption_image(image_bytes, context_text)` | Gọi GPT-4o hoặc Claude vision (chọn qua `VISION_PROVIDER`), trả về caption |
| `excel_ingest.build_intermediate(sheets, images)` | Ghép text + ảnh theo đúng vị trí thành markdown thô |
| `excel_ingest.refine_with_llm(raw_markdown, use_online_model)` | Gọi text LLM hiện có (client/model đã khởi tạo trong `main.py`) để làm sạch format |
| `manifest.py` | Tính sha256 nội dung file, so sánh với manifest đã lưu để quyết định skip/reprocess |

## Endpoints mới (trong `main.py`)

- `POST /ingest-excel`
  - Body: `{"use_online_model": 0, "force": false}`
  - Quét `EXCEL_SOURCE_DIR` (glob `*.xlsx`), bỏ qua file đã xử lý và không đổi hash (trừ khi
    `force=true`), xử lý phần còn lại.
  - Response: `{"processed": [...], "skipped": [...], "failed": [{"file": ..., "error": ...}]}`.
- `POST /ingest-excel/upload`
  - Multipart upload 1 file `.xlsx` ad-hoc, luôn xử lý ngay (force=true, không qua manifest skip).

## Error handling

- Mỗi file xử lý độc lập trong try/except riêng — 1 file lỗi (Excel hỏng, vision API lỗi, text LLM
  lỗi) không chặn các file khác; lỗi được thu vào `failed` trong response, service không crash.
- Manifest chỉ cập nhật **sau khi toàn bộ pipeline của file đó thành công** → file lỗi tự động được
  thử lại ở lần chạy `/ingest-excel` kế tiếp mà không cần cờ `force`.
- Thiếu API key cho `VISION_PROVIDER` đã cấu hình (`OPENAI_API_KEY` hoặc `ANTHROPIC_API_KEY`) →
  trả `HTTPException(503)` ngay khi endpoint được gọi, nêu rõ thiếu key nào — không âm thầm bỏ qua
  ảnh và tạo Markdown thiếu nội dung quan trọng.
- Không retry tự động trong v1 (YAGNI) — người dùng gọi lại `/ingest-excel` khi cần, manifest đảm
  bảo chỉ các file thất bại mới được xử lý lại.

## Testing

- Unit test `extract_workbook` với file `.xlsx` fixture nhỏ (1 sheet, 2 dòng, 1 ảnh nhúng) — kiểm
  tra text từng dòng + ảnh + vị trí neo trích xuất đúng.
- Unit test `manifest` — file không đổi nội dung → skip; đổi nội dung → hash khác → xử lý lại.
- Unit test `build_intermediate` với dữ liệu giả (rows + caption có sẵn) → kiểm tra markdown output
  đúng cấu trúc và vị trí ảnh.
- Vision LLM và text LLM refiner được mock trong test (không gọi API thật trong CI). Validate thật
  bằng tay với vài file Excel mẫu thực tế trong quá trình triển khai.

## Cấu hình mới

Thêm vào `.env.example`:
```
VISION_PROVIDER=openai        # openai | anthropic
ANTHROPIC_API_KEY=
```

Thêm vào `docker-compose.yml` (service `knowledge_service`, mục `environment`):
```
VISION_PROVIDER=${VISION_PROVIDER:-openai}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
OPENAI_VISION_MODEL=${OPENAI_VISION_MODEL:-gpt-4o}
ANTHROPIC_VISION_MODEL=${ANTHROPIC_VISION_MODEL:-claude-sonnet-4-5}
EXCEL_SOURCE_DIR=/app/project_data/excel_sources
```

Thêm vào `services/knowledge_service/requirements.txt`:
```
openpyxl
anthropic
```

Thêm vào `.gitignore` (root):
```
excel_sources/
```

## Phạm vi không thực hiện (out of scope cho v1)

- Không tự động trigger `/ingest` (embedding vào Qdrant) sau khi `/ingest-excel` chạy xong — người
  dùng gọi riêng, tách trách nhiệm rõ ràng giữa "curate" và "index".
- Không retry tự động khi LLM/vision API lỗi tạm thời.
- Không hỗ trợ định dạng `.xls` cũ (chỉ `.xlsx`).
- Không xử lý ảnh dạng chart/pivot chart nhúng trong Excel (chỉ ảnh raster thông thường trong
  `xl/media/`).
