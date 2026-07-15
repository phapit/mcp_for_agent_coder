# Phân tích sự cố (Postmortems)

Mỗi mục ghi lại: sự cố, root cause, tác động, cách xử lý, hành động phòng ngừa —
theo [[Business-Rules]] ("không bao giờ lặp lại cùng một bug").

---

## 2026-07-15 — Câu hỏi Session cần đủ ngữ cảnh

**Hiện tượng**: Với câu hỏi ngắn `Session tồn tại tối đa bao nhiêu ngày?`, `/answer` có thể trả lời không biết. Khi bổ sung ngữ cảnh rõ ràng như `Session duration 28 days guest registered users`, service trả lời đúng `28 ngày`.

**Kết luận**: Đây không phải lỗi của Qdrant, Ollama hay dữ liệu tài liệu. Nguyên nhân là câu hỏi của End User chưa đủ ngữ cảnh để semantic search chọn đúng đoạn liên quan.

**Lưu ý vận hành**: Trước khi thay đổi embedding, retrieval, `limit` hoặc nâng model, cần thử lại bằng câu hỏi có thêm thuật ngữ và phạm vi nghiệp vụ. Chỉ xem xét sửa hệ thống khi câu hỏi đã rõ nhưng `/search` vẫn không trả về chunk chứa câu trả lời.

**Trạng thái**: Không thay đổi code; ghi nhận như một lưu ý về chất lượng prompt của End User.

---

## 2026-07-14 — `docker-compose.yml` tham chiếu thư mục service không tồn tại

**Sự cố**: `docker-compose.yml` định nghĩa build context `./services/knowledge_service` và
`./services/agent_service`, nhưng 2 thư mục này chưa từng được tạo — chỉ có 1 file `main.py` gộp
chung ở root (đã cài `git ops` nhưng `/search`, `/answer` chỉ là `pass`). Chạy `docker compose up`
tại thời điểm đó sẽ fail ngay ở bước build vì không tìm thấy `Dockerfile` trong context.

**Root cause**: Tài liệu kiến trúc (`Architecture.md`) và hạ tầng (`docker-compose.yml`) được viết
theo mô hình 2 microservice, nhưng phần code triển khai ban đầu lại đi theo hướng gộp 1 file —
không có bước đối chiếu giữa 3 nguồn (docs / compose / code) trước khi coi là "xong".

**Tác động**: Dự án không thể khởi chạy được ở trạng thái này; mọi mô tả trong README/AGENTS.md về
hệ thống đang hoạt động là chưa đúng thực tế.

**Cách xử lý**: Tạo `services/knowledge_service/` và `services/agent_service/` với
`main.py` + `requirements.txt` + `Dockerfile` riêng, cài đặt đầy đủ `/ingest`, `/search`, `/answer`
(knowledge_service) và giữ nguyên `/git/status`, `/git/branch` + thêm `/consult`
(agent_service). Xóa `main.py`/`Dockerfile`/`requirements.txt` cũ ở root vì đã thành dead code.
Quyết định và phương án thay thế được ghi tại `docs/architecture_handoff.md`.

**Hành động phòng ngừa**: Trước khi đánh dấu 1 thay đổi hạ tầng/kiến trúc là hoàn tất, phải đối
chiếu cả 3 nguồn: tài liệu mô tả (`docs/Architecture.md`), cấu hình hạ tầng (`docker-compose.yml`),
và code thực tế — nếu 1 trong 3 không khớp thì chưa được coi là Done (áp dụng
[[Business-Rules]] mục Definition of Done).
