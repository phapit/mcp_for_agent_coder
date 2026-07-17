# Tính năng: Yêu cầu khách hàng → Gói ngữ cảnh cho agent

Cập nhật: 2026-07-17

## Mục đích

Tiếp nhận yêu cầu từ khách hàng (thêm tính năng / sửa lỗi), truy xuất các **đặc tả hiện có liên quan** trong kho tri thức (Qdrant) và đóng gói thành **gói ngữ cảnh có trích dẫn** cho agent PM / Coder / Tester. Mục tiêu: loại bỏ ảo giác — agent chỉ làm việc trên trích đoạn đặc tả nguyên văn, không suy đoán về hành vi hiện có, không phá vỡ tính năng đã đặc tả.

## Cơ chế chống ảo giác

1. **Trích đoạn nguyên văn có nguồn**: mỗi trích đoạn kèm file nguồn, heading, số dòng và điểm liên quan (hybrid dense + BM25, rerank đa ngôn ngữ).
2. **Tuyên bố rõ khi không có đặc tả**: nếu không trích đoạn nào vượt ngưỡng (`MIN_SCORE_THRESHOLD` / `MIN_RERANK_SCORE`), gói ngữ cảnh chứa cảnh báo "KHÔNG tìm thấy đặc tả — không suy đoán về hành vi hiện có" thay vì im lặng.
3. **Quy tắc bắt buộc theo vai trò** (nhúng trong markdown):
   - Chung: chỉ coi trích đoạn là "hành vi hiện có"; trích dẫn dạng `[n]`; thiếu thông tin thì ghi "chưa có đặc tả" và đặt câu hỏi, không bịa; **khóa phạm vi** — không đề xuất công nghệ/thư viện/luồng xử lý không có trong trích đoạn, thứ mới phải đánh dấu ĐỀ XUẤT MỚI cần xác nhận.
   - PM: đối chiếu xung đột/trùng lặp, viết đặc tả cập nhật đánh dấu GIỮ NGUYÊN / THAY ĐỔI / MỚI.
   - Coder: giới hạn phạm vi thay đổi theo tài liệu bị ảnh hưởng, kiểm tra mâu thuẫn trước khi code.
   - Tester: test case cho hành vi mới + regression test cho hành vi hiện có, mỗi test ghi căn cứ.
4. **Quy tắc đối chiếu chéo theo loại yêu cầu** (theo `docs/Huong_dan_su_dung_NotebookLM_hieu_qua.md` §2):
   - `feature`: đánh giá tác động trước — liệt kê component/endpoint/luồng trong trích đoạn sẽ bị ảnh hưởng và ràng buộc thiết kế nào giới hạn cách làm.
   - `bug`: xác định hành vi ĐÚNG theo đặc tả trước khi sửa; nếu trích đoạn ghi nhận lỗi/edge case tương tự, nêu nguyên nhân và cách xử lý đã có.

Cùng nguyên tắc khóa phạm vi này, endpoint `POST /notebook-reports` (xem `routes_notebooklm.py`) tự động prepend chỉ thị grounding (`GROUNDING_PREAMBLE` trong `notebooklm_service.py`) vào mọi prompt gửi NotebookLM: chỉ dùng source trong notebook, trích dẫn nguồn, không suy đoán ngoài tài liệu. Giới hạn 1024 ký tự vẫn chỉ áp dụng cho prompt của người dùng.

## API (knowledge_service, yêu cầu `X-API-Key`)

| Method | Endpoint | Mô tả |
|---|---|---|
| POST | `/client-requests/preview` | Tra cứu thuần túy — truy xuất và trả `context` (kèm `markdown` nếu có `?role=`), **không lưu bản ghi**. Body giống `/client-requests`. |
| POST | `/client-requests` | Tạo yêu cầu và phân tích ngay. Body: `{title, description, request_type: "feature"\|"bug", project?, requester?, limit?}` (mặc định 8 trích đoạn). Trả 201 kèm `context`. |
| GET | `/client-requests?limit=` | Danh sách rút gọn, mới nhất trước (không kèm nội dung trích đoạn). |
| GET | `/client-requests/{id}` | Bản ghi đầy đủ kèm gói ngữ cảnh gần nhất. |
| GET | `/client-requests/{id}/context?role=pm\|coder\|tester` | Gói ngữ cảnh + `markdown` sẵn để nạp thẳng vào prompt agent theo vai trò. |
| POST | `/client-requests/{id}/reanalyze?limit=` | Chạy lại truy xuất — dùng sau khi ingest thêm/cập nhật đặc tả. |

Cấu trúc `context`: `{analyzed_at, query, has_related_specs, warning, related_documents[{source, excerpt_count, best_score}], excerpts[{text, source, heading, start_line, end_line, score}], retrieval}`.

Ví dụ dùng cho agent:

```bash
curl -s "http://localhost:8002/client-requests/<id>/context?role=coder" \
  -H "X-API-Key: $SERVICE_API_KEY" | jq -r '.markdown'
```

Dùng `/client-requests/preview` khi chỉ cần tra cứu (không cần theo dõi lại
sau này); dùng `/client-requests` khi cần lưu để nhiều agent tham chiếu qua
`request_id` hoặc để `reanalyze` sau khi ingest thêm đặc tả.

## Lưu trữ

MongoDB collection `client_requests` (đổi qua env `MONGODB_CLIENT_REQUESTS_COLLECTION`), một document mỗi yêu cầu, index unique theo `request_id`.

## Frontend

Menu **"Yêu cầu khách hàng"** (`/client-requests`): form gửi yêu cầu; danh sách; chi tiết gồm tài liệu bị ảnh hưởng, trích đoạn đặc tả, tab PM/Coder/Tester, nút **Sao chép Markdown** để dán vào prompt agent, nút **Phân tích lại**.

## Quy trình khuyến nghị

1. Ingest đầy đủ đặc tả vào kho (`/ingest`, `/ingest-excel`, `/ingest-spreadsheet`).
2. Nhập yêu cầu khách qua UI hoặc `POST /client-requests`.
3. Nếu kết quả báo "chưa có đặc tả" nhưng bạn biết là có: kiểm tra tài liệu đã ingest chưa, rồi bấm "Phân tích lại".
4. Lấy markdown theo vai trò và nạp cho agent tương ứng.

## Yêu cầu vận hành: rerank đa ngôn ngữ

Yêu cầu khách nhập bằng **tiếng Việt** trong khi đặc tả phần lớn là **tiếng Anh**; embedding mặc định (`all-MiniLM-L6-v2`) chỉ tốt cho tiếng Anh nên truy vấn Việt→Anh không vượt ngưỡng nếu thiếu rerank. Vì vậy **bắt buộc bật `RERANK_ENABLED=1`** trong `.env` (model `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` đã là mặc định). Đánh đổi: mỗi lần search chậm hơn (cross-encoder trên CPU), tải model ~500MB vào `app_data/hf_cache` lần đầu.

Giải pháp căn cơ hơn (chưa làm): chuyển sang embedding đa ngôn ngữ (ví dụ `paraphrase-multilingual-MiniLM-L12-v2`) và re-ingest toàn bộ kho.

## Kiểm thử

`services/knowledge_service/tests/test_client_requests.py` (15 test): tạo yêu cầu có/không có đặc tả liên quan, preview có/không lưu, validate `request_type`/`role`, markdown theo vai trò, quy tắc khóa phạm vi + quy tắc theo loại yêu cầu, 404, reanalyze sau khi có đặc tả mới, cảnh báo cấm suy đoán. Chạy trong container:

```bash
docker exec knowledge_service sh -c \
  'cd /app/project_data/services/knowledge_service && python -m pytest tests/test_client_requests.py -q'
```
