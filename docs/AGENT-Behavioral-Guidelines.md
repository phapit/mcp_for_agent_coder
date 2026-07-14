# Hướng dẫn hành vi cho AI Agent

Tài liệu này tổng hợp các quy tắc và nguyên tắc cốt lõi mà AI Agent phải tuân theo trong quá trình phân tích, viết mã và tương tác.

## Cấu trúc dự án và quy tắc tương tác

File `AGENTS.md` gốc chứa các quy tắc về:
- Cấu trúc thư mục của dự án.
- Cách sử dụng Skills để tối ưu chi phí.
- Quy trình kiểm thử UI và API.

## Nguyên tắc phát triển phần mềm

Các nguyên tắc này được lấy từ `Behavioral-guidelines-to-reduce-common-LLM-coding-mistakes.md` và `Behavioral-guidelines-EXAMPLES.md`, nhằm giảm thiểu các lỗi phổ biến khi lập trình của LLM.

1.  **Think Before Coding (Suy nghĩ trước khi lập trình)**: Luôn làm rõ các giả định, yêu cầu và các hướng tiếp cận khác nhau trước khi viết mã.
2.  **Simplicity First (Ưu tiên sự đơn giản)**: Chỉ viết mã giải quyết vấn đề hiện tại, không thêm các tính năng hoặc sự phức tạp không cần thiết.
3.  **Surgical Changes (Thay đổi chính xác)**: Khi sửa đổi mã nguồn, chỉ thay đổi những gì thực sự cần thiết, giữ nguyên phong cách và cấu trúc hiện có.
4.  **Goal-Driven Execution (Thực thi hướng mục tiêu)**: Xác định các tiêu chí thành công rõ ràng và có thể kiểm chứng cho mỗi tác vụ.

Những nguyên tắc này giúp đảm bảo AI Agent hoạt động một cách thận trọng, hiệu quả và tạo ra mã nguồn chất lượng cao, dễ bảo trì.