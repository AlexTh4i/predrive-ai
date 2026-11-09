# Ghi chú tích hợp Web Admin M3

Web Admin dùng hợp đồng M3 trong đặc tả Web Admin được giao, với base path `/api/v1`. [Hợp đồng chung hiện có](../../docs/api-contract.md) mô tả MVP v0.2, nên cần thống nhất bản M3 với thành viên backend trước khi dùng dữ liệu thật.

| Nội dung | Hợp đồng MVP trong repo | Hợp đồng Web Admin M3 |
| --- | --- | --- |
| Truyền dữ liệu trực tiếp | WebSocket `/ws/monitor` cho thiết bị tài xế | SSE `GET /api/v1/live/stream`, sự kiện `driver_state` và `alert` |
| Định dạng JSON | snake_case, kết quả phân tích từng frame | camelCase, trạng thái phiên, sự kiện và thống kê |
| Xác thực | Phiên WebSocket thử nghiệm | `POST /auth/login`, `GET /auth/me`, JWT Bearer và phân quyền theo tổ chức |
| Enum | `NOT_EVALUATED`, mức cảnh báo `NONE/INFO/WARNING/CRITICAL` | `OFFLINE`, `DISCONNECTED`, mức sự kiện `WARNING/CRITICAL` và vòng đời `OPEN/ESCALATED/CLOSED` |
| Nghiệp vụ Admin | Chưa có endpoint | `/live`, `/events`, `/drivers`, `/stats/*`, `/settings` |

## Quy ước phía web

- `GET /events` dùng `page` bắt đầu từ 1, `acked=true|false`, lọc theo `capturedAt`, thứ tự mới nhất trước. `from` và `to` là hai mốc bao gồm, quy đổi từ đầu và cuối ngày Việt Nam sang UTC.
- Dashboard lấy tối đa 5 cảnh báo đủ điều kiện trong 7 ngày gần nhất. `REST_CLAIM_REJECTED` và `delayed=true` được xem trong lịch sử. Ghi nhận liên hệ dựa trên `ackAt`, độc lập với vòng đời `status`. `POST /events/{id}/ack` gửi `{ note }` và đồng bộ lại từ bản ghi trả về.
- `/stats/hourly` và `/drivers/{id}/stats` cần trả `hour` theo `Asia/Ho_Chi_Minh`. Web giả định `tooDarkRate` và `unavailableRate` là tỷ lệ từ 0 đến 1. Do M3 chưa có endpoint xu hướng, web lấy `total` từ `GET /events?page=1&pageSize=1` cho từng ngày hoặc nhóm 7 ngày liên tiếp.
- `GET /settings` phục vụ cả hai vai trò điều hành để đọc chu kỳ heartbeat. `PUT /settings` yêu cầu manager. Form đổi phút sang giây cho các ngưỡng lái và giữ nguyên `heartbeatIntervalSec` trong payload.
- JWT do backend cấp được giữ trong bộ nhớ và `sessionStorage` của tab, tách biệt khóa demo. Backend chịu trách nhiệm kiểm tra JWT, vai trò, quyền ghi và `organizationId` trên mọi request và kết nối SSE. Đăng xuất xóa phiên cục bộ. API M3 chưa mô tả refresh token hay thu hồi JWT.
- Ứng dụng web không truy cập camera. `avatarUrl` trong hồ sơ dành cho ảnh đại diện do backend cung cấp. Bản đồ vị trí là tùy chọn và chưa triển khai.

## Giao tiếp SSE

- Server trả `Content-Type: text/event-stream`, giữ kết nối mở và flush sự kiện ngay. Nên gửi comment keep-alive khoảng 15–30 giây để phân biệt luồng yên lặng với kết nối treo. Web thử lại nếu luồng im lặng 75 giây, đóng hoặc gặp lỗi mạng. Khoảng thử lại tăng từ 1 đến tối đa 15 giây.
- Khi bắt đầu hoặc kết nối lại, web lấy snapshot trạng thái, cài đặt và cảnh báo gần đây, đồng thời đệm thông điệp SSE đến trong lúc đọc snapshot. Bản ghi cảnh báo hợp nhất theo ID. M3 chưa quy định replay qua `Last-Event-ID`, nên snapshot bù dữ liệu hiển thị khi mất luồng.
- Web chỉ hiện trạng thái đã xác nhận khi SSE hoạt động và heartbeat của phiên còn mới. Khi hết hạn quá hai chu kỳ heartbeat, web hiện **Chưa xác nhận** cho trạng thái phiên đang chạy. Backend mới có quyền kết luận `DISCONNECTED` và tạo sự kiện mất kết nối thật.
- CORS khác origin cần cho phép origin của admin, `Authorization`, `Content-Type` và các phương thức GET, POST, PUT. Proxy không được giữ SSE trong bộ đệm. Dùng HTTPS khi triển khai.

Đã kiểm tra REST và SSE qua proxy Vite với máy chủ fixture, gồm Bearer, `driver_state`/ `alert`, `DISCONNECTED`, sự kiện gửi muộn, ghi nhận liên hệ, đóng luồng rồi kết nối lại, heartbeat cũ và 401. Fixture cũng kiểm tra bộ lọc lịch sử, khoảng ngày Việt Nam chuyển sang UTC, lỗi và thử lại từng phần thống kê, cùng payload cài đặt quy đổi từ phút sang giây.

Cần đối chiếu với FastAPI M3 thật về schema, dữ liệu và công thức thống kê, sắp xếp sự kiện, chính sách ghi theo vai trò, cách ly nhiều tổ chức, CORS và hành vi SSE qua proxy triển khai.
