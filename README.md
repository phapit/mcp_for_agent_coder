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

### Khởi động hệ thống
```
docker compose up -d --build
```

### Pull model cho Ollama (chạy 1 lần sau khi container `ollama` đã chạy)
`knowledge_service` hỗ trợ cả OpenAI (`gpt-4o-mini`, online) và Ollama (local, mặc định `llama3.2:3b`) cho endpoint `/answer` (chọn qua tham số `use_online_model`: `0` = Ollama, `1` = OpenAI). Trước khi dùng nhánh Ollama, cần pull model về:

```
docker exec -it ollama ollama pull llama3.2:3b
```

Đổi model bằng cách set biến môi trường `OLLAMA_MODEL` trước khi `docker compose up` (ví dụ `qwen2.5:7b`), rồi pull đúng model đó.