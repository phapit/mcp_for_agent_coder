# Phân tích sự cố (Postmortems)

Mỗi mục ghi lại: sự cố, root cause, tác động, cách xử lý, hành động phòng ngừa —
theo [[Business-Rules]] ("không bao giờ lặp lại cùng một bug").

---

## 2026-07-16 — DNS "ollama" trỏ nhầm container trên mạng chung

**Hiện tượng**: `/answer` với model local (`use_online_model=0`) luôn trả 502; log knowledge_service ghi `model 'llama3.2:3b' not found` dù `docker exec ollama` xác nhận model đã pull.

**Root cause**: knowledge_service tham gia đồng thời 2 mạng (`ai_agent_net` và `docker_global_bridge`). Container `backend-ollama-1` của một project khác có alias `ollama` trên `docker_global_bridge`, nên Docker DNS resolve tên `ollama` sang container đó (172.18.0.14) thay vì ollama của repo (172.20.0.3). Container nhầm không có model `llama3.2:3b`.

**Tác động**: Toàn bộ tính năng trả lời bằng LLM local không hoạt động; chỉ đường online (OpenAI) dùng được. Lỗi tồn tại âm thầm vì health-check `/health/ready` chỉ kiểm tra endpoint `/models` trả HTTP < 500, không kiểm tra model cụ thể.

**Cách xử lý**: Thêm alias riêng `wiki-ollama` cho service ollama trên `ai_agent_net` và đổi `OLLAMA_BASE_URL=http://wiki-ollama:11434/v1` trong `docker-compose.yml`; recreate 2 container. Xác minh bằng `socket.gethostbyname('wiki-ollama')` từ trong container.

**Hành động phòng ngừa**: Không dùng tên generic (`ollama`, `mongodb`, `kafka`…) làm hostname khi container tham gia mạng chung nhiều project — luôn đặt alias có prefix project. Khi debug lỗi "model not found", kiểm tra DNS resolve trước khi nghi ngờ dữ liệu.

---

## 2026-07-16 — Bật rerank với model EN-only làm mất toàn bộ kết quả tìm kiếm

**Hiện tượng**: Sau khi bật `RERANK_ENABLED=1` với model mặc định ban đầu `cross-encoder/ms-marco-MiniLM-L-6-v2`, mọi câu hỏi tiếng Việt qua `/search`, `/answer` trả về rỗng/404. Đo bằng bộ eval chuẩn: retrieval hit rate rơi từ 50% (không rerank) xuống 0%.

**Root cause**: ms-marco cross-encoder chỉ được huấn luyện trên tiếng Anh; với cặp (câu hỏi tiếng Việt, chunk tiếng Anh) nó chấm xác suất < 0.3 cho mọi ứng viên, khiến ngưỡng `MIN_RERANK_SCORE=0.3` loại hết kết quả trước khi vào context.

**Cách xử lý**: Đổi sang model đa ngôn ngữ `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` (mặc định mới trong `docker-compose.yml` và `retrieval.py`). Kết quả eval: retrieval hit rate 100%, refusal rate câu ngoài phạm vi 100% (chi tiết: `docs/Knowledge-Ingestion.md` §7).

**Hành động phòng ngừa**: Mọi thay đổi model trong pipeline retrieval (embedding, reranker) phải chạy `scripts/rag_eval.py` trước/sau để so sánh, vì bộ eval có sẵn câu hỏi tiếng Việt sẽ lộ ngay vấn đề ngôn ngữ. Ghi rõ ràng buộc "đa ngôn ngữ" trong `.env.example`.

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
