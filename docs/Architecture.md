## Dưới đây là danh sách chi tiết các công nghệ và vai trò của chúng trong hệ thống:

# 1. Hạ tầng và Containerization (Infrastructure & Containerization)
Docker & Docker Compose: Đây là nền tảng của toàn bộ dự án. Docker được sử dụng để đóng gói mỗi dịch vụ (như knowledge_service, agent_service, qdrant) vào một container độc lập. Docker Compose giúp định nghĩa và khởi chạy toàn bộ hệ thống đa container này chỉ bằng một lệnh duy nhất, đảm bảo môi trường phát triển và triển khai nhất quán.

# 2. Backend và API
Python 3.11: Là ngôn ngữ lập trình chính được sử dụng để xây dựng logic cho các dịch vụ backend.
FastAPI: Một web framework hiệu suất cao của Python, được dùng để xây dựng các API cho knowledge_service và agent_service. Nó giúp tạo ra các endpoint một cách nhanh chóng và có tài liệu API (Swagger UI) tự động.
Uvicorn: Là một máy chủ ASGI (Asynchronous Server Gateway Interface) tốc độ cao, được dùng để chạy các ứng dụng FastAPI.

# 3. Trí tuệ nhân tạo & Machine Learning (AI/ML)
Qdrant: Một cơ sở dữ liệu vector (Vector Database) hiệu suất cao. Vai trò của nó là lưu trữ các vector embedding được tạo ra từ tài liệu dự án. Nó cho phép agent_service thực hiện tìm kiếm ngữ nghĩa (semantic search) cực kỳ nhanh chóng để tìm ra các thông tin liên quan.
Sentence-Transformers (Hugging Face): Một thư viện Python dùng để tạo ra các vector embedding chất lượng cao từ văn bản. Trong dự án, nó chuyển đổi các tài liệu Markdown và các câu hỏi của người dùng thành dạng vector mà Qdrant có thể hiểu và tìm kiếm.
LangChain: Một framework mạnh mẽ giúp đơn giản hóa việc xây dựng các ứng dụng AI phức tạp. Nó được sử dụng trong knowledge_service để thực hiện các chuỗi xử lý như: tải tài liệu, chia nhỏ văn bản, và nạp vào Qdrant.
OpenAI / Anthropic APIs: Đây là "bộ não" của agent_service. Dịch vụ này sẽ gọi đến API của các mô hình ngôn ngữ lớn (LLM) như GPT-4 (OpenAI) hoặc Claude (Anthropic) để thực hiện các tác vụ phức tạp như trả lời câu hỏi, phân tích, và sinh mã nguồn.

# 4. Công cụ và Tích hợp (Tooling & Integrations)
Git & GitPython: Git là hệ thống quản lý phiên bản mã nguồn. agent_service sử dụng thư viện GitPython để có thể tự động thực hiện các thao tác như kiểm tra trạng thái, tạo nhánh mới, và commit thay đổi, giống như một lập trình viên thực thụ.
Obsidian & Markdown: Obsidian được định vị là kho tri thức trung tâm (Project Wiki), nơi các lập trình viên con người quản lý toàn bộ tài liệu dự án dưới định dạng Markdown. Các agent AI sẽ đọc và học từ chính các file Markdown này.

## Tóm lại
`hệ thống này là một sự kết hợp tinh vi giữa các dịch vụ backend (Python/FastAPI), cơ sở dữ liệu vector (Qdrant), các mô hình AI (OpenAI, Sentence-Transformers), và các công cụ phát triển phần mềm (Git, Docker) để tạo ra một trợ lý kỹ sư phần mềm tự động.`

## Kiến trúc hệ thống

Tài liệu này mô tả kiến trúc tổng thể của hệ thống AI Engineering Agent.

## Tổng quan

Hệ thống được thiết kế để tự động hóa các tác vụ phát triển phần mềm bằng cách sử dụng một AI Agent (ví dụ: Codex, Claude) có khả năng đọc hiểu tài liệu dự án, phân tích mã nguồn và tạo ra các Pull Request.

## Luồng hoạt động

Kiến trúc hệ thống bao gồm các thành phần chính tương tác với nhau theo luồng sau:
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
## Vai trò của từng thành phần

- **Obsidian**: Đóng vai trò là kho tri thức trung tâm (Project Wiki), chứa mọi thông tin về dự án từ kiến trúc, quy tắc nghiệp vụ, đến lịch sử sự cố.
- **Knowledge Curator (NotebookLM)**: Chịu trách nhiệm tóm tắt, truy vấn và tạo biểu đồ tri thức từ các tài liệu trong Obsidian.
- **Markdown Knowledge Canonical Docs**: Là các tài liệu chuẩn hóa được tạo ra từ NotebookLM, sẵn sàng cho việc tạo embeddings.
- **Qdrant (Vector Store)**: Lưu trữ các embeddings của tài liệu, cho phép AI Agent tìm kiếm và truy xuất thông tin ngữ nghĩa một cách nhanh chóng.
- **Code Analyzer & AI Developer**: Các agent thực thi việc phân tích mã nguồn và phát triển tính năng mới.
- **Git Repository**: Nơi lưu trữ mã nguồn và các thay đổi do AI Agent tạo ra.