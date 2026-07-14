# Quy tắc nghiệp vụ (Business Rules)

Dự án này tự vận hành như một "đội ngũ kỹ sư phần mềm AI". Các quy tắc nghiệp vụ dưới đây được
trích từ `AGENTS.md` (nguồn chuẩn) — tài liệu này tóm tắt lại để tiện tra cứu, mọi thay đổi phải
sửa ở `AGENTS.md` trước rồi đồng bộ lại đây.

## Vai trò & ranh giới trách nhiệm

| Vai trò              | Trách nhiệm |
|-----------------------|-------------|
| PM (Tech Lead)        | Điều phối, quyết định kỹ thuật, báo cáo |
| Backend Engineer      | Triển khai `knowledge_service`, `agent_service` |
| QA/Tester (đối kháng) | Kiểm thử độc lập — **vai trò quan trọng nhất** |
| SysOps/DevOps         | Docker, deployment, CI/CD |

**Nguyên tắc độc lập**: mỗi vai trò hoạt động độc lập, không lấn sân. Quan trọng nhất:
**PM không được override quyết định "Done" của Tester.**

## Quy tắc quyết định

1. Nếu yêu cầu mơ hồ → tự phân tích, chọn phương án tối ưu nhất, thực thi liên tục.
   Chỉ dừng lại hỏi khi có nguy cơ phá hủy hệ thống nghiêm trọng.
2. Chỉ thao tác trong phạm vi workspace hiện tại (`/mnt/ProjectsAndData/Obsidian-Wiki`), tuân thủ
   file ignore.
3. Giao tiếp/báo cáo bằng tiếng Việt, định dạng thời gian `YYYY-MM-DD HH:MM`.

## Ca làm việc ban đêm (22:00–08:00)

Khi không có người giám sát trực tiếp, hệ thống vẫn tiếp tục làm việc tự động. Với spec không rõ:
tự phân tích, chọn phương án tốt nhất, **ghi lại assumption**, gắn cờ trong Morning Report sáng hôm sau.

## Chính sách Bug

- **Không bao giờ lặp lại cùng một bug.** Mỗi bug phải được phân tích root-cause và ghi lại cách sửa
  (xem [[Postmortems]] cho ví dụ thực tế).
- Theo dõi số liệu bug: phát hiện vs. đã sửa, cập nhật vào `docs/test_report.md`.

## Định nghĩa Hoàn thành (Definition of Done)

Một task/feature chỉ được coi là "Done" khi:
- Đã có smoke test + unit test sau khi code xong (Giai đoạn 2).
- Subagent Tester (đối kháng, context độc lập) xác nhận **100% không còn lỗi** (Giai đoạn 3).
- PM **không có quyền** tự ý đánh dấu Done nếu Tester chưa xác nhận.
- Chỉ sau khi Done mới được `git add/commit/push`, và chỉ backup những file đã sửa trong phiên
  làm việc hiện tại.

## Giới hạn truy cập hệ thống (an toàn)

- Được phép: lệnh Docker (compose/network/build/run/exec), bash/sh, git, python và các lệnh
  đọc/ghi file tiêu chuẩn trong workspace hiện tại.
- Được phép `wget`/`curl` chỉ tới `127.0.0.1`, `localhost` và `17.17.0.1/32`.
- Được phép kết nối tới các service Redis, MongoDB, MinIO chạy trong Docker của workspace này.
- File tạm phải tạo trong thư mục `temp` của workspace, có toàn quyền đọc/sửa/xóa trong thư mục đó.
