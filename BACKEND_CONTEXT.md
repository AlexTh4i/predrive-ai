# CONTEXT 03 – Backend / System Engineer

## Vai trò và mục tiêu
Bạn phụ trách **FastAPI AI gateway**, quản lý phiên WebSocket, xác thực/quyền, tích hợp module `ai/`, lưu metadata chuyến đi/sự kiện, cung cấp API dashboard và gửi thông báo admin ở giai đoạn sau. Không train AI hay viết UI React.

## Công nghệ
Python + FastAPI/Uvicorn, Pydantic, WebSocket, OpenCV/Pillow để decode an toàn, PostgreSQL (ưu tiên Supabase managed khi lên cloud) hoặc SQLite để phát triển nội bộ, Alembic/SQLAlchemy khi cần. Telegram Bot qua **server-side** (không lộ bot token). Khi tích hợp AI nặng cân nhắc inference worker/queue và đo latency.

## Nhiệm vụ theo thứ tự
**B1 – Gateway MVP:** `GET /health`, `POST /api/v1/sessions` để tạo session thử nghiệm, `WS /ws/monitor?session_id=...`. Giới hạn số kết nối, fps, kích thước message, độ phân giải, kiểm tra JSON/JPEG base64, frame_id, timestamps; trả `analysis_result` với `NOT_EVALUATED`, `mock-v0`, không bịa AI. Đóng session khi client rời; có heartbeat/timeout và bỏ frame quá cũ để tránh backlog. Chưa lưu video.

**B2 – AI Integration:** gọi `ai.analyze_frame` theo contract, map trạng thái; xử lý timeout/crash/không có khuôn mặt → `MONITORING_UNAVAILABLE`, tuyệt đối không tự trả `NORMAL`. Ghi log hiệu năng và metric ẩn danh; bảo vệ khỏi CPU/GPU overload; không dùng xử lý chặn dài trong event loop.

**B3 – Database/Auth:** thực thể tối thiểu `users`, `drivers`, `vehicles`, `trips`, `events`, `alerts` (và `model_versions` nếu cần). Driver thuộc organization; role driver/admin; chỉ admin cùng tổ chức xem dữ liệu tương ứng. API thống kê phải tính thời gian giám sát hợp lệ và tỷ lệ sự kiện trên giờ. Dùng migration, indexes và phân quyền; không tin driver_id/role do client tự gửi.

**B4 – Notification:** với sự kiện nghiêm trọng đã xác định, lưu idempotency key để tránh thông báo trùng; server gửi Telegram qua token trong env/secret manager. Có trạng thái delivery/ack, rate limit và cơ chế retry. Đây là kênh phụ, không thay cảnh báo tại xe; ưu tiên dữ liệu tối thiểu, không gửi video mặt.

**B5 – Deploy:** tách HTTP API/WS và inference worker khi cần, HTTPS/WSS, xác thực trước Internet công khai, CORS hạn chế origin, request/body limits, logging không chứa video, metrics latency (p50/p95), reconnect, bảo vệ access token. Backend/server-free cloud **không đồng nghĩa có GPU miễn phí 24/7**; MVP chạy LAN trên laptop/PC trước.

## Schema dữ liệu gợi ý
- `trips`: `id`, `driver_id`, `vehicle_id`, `started_at`, `ended_at`, `valid_monitoring_seconds`, `status`, `model_version`.
- `events`: `id`, `trip_id`, `frame_id`, `event_type`, `severity`, `detected_at`, `image_quality`, `model_version`, `review_status`.
- `alerts`: `id`, `event_id`, `channel`, `sent_at`, `delivery_status`, `acknowledged_at`.
- Giữ dữ liệu tối thiểu; quy định thời hạn lưu và quyền xóa/truy cập. Video mặt không mặc định lưu.

## Bàn giao cần có
- `backend/app/main.py`, route health/session/ws và Pydantic schemas.
- `backend/tests/`: valid frame, invalid payload, oversized image, duplicate frame, stale frame, disconnect, AI timeout.
- `backend/README.md` và `.env.example` không chứa secrets.
- `docs/api-contract.md` là nguồn quy ước chung đã thống nhất với AI + Frontend.
- Sau B3: database migration, auth, tài liệu dashboard endpoints.

## Tiêu chí nghiệm thu milestone backend đầu
1. `/health` phản hồi, session tạo được bằng API thử nghiệm.
2. WebSocket phản hồi `NOT_EVALUATED` đúng schema, đo latency.
3. Payload lỗi/quá lớn không làm server crash.
4. Không lưu video mặt và không gửi sự kiện giả lên admin.
5. Có hướng dẫn chạy server LAN và giải thích điều kiện HTTPS/WSS khi thử điện thoại thực.

## Bối cảnh chung và hợp đồng tích hợp (PHẢI TUÂN THỦ)
- Dự án: **PREDRIVE AI**, bản MVP nghiên cứu hệ thống giám sát dấu hiệu buồn ngủ/mất tập trung của tài xế.
- Một website **PWA** chạy trên Safari iPhone và Chrome Android; AI **chạy tập trung trên Python server**, không chạy mô hình nhận diện trên trình duyệt.
- Luồng chính: `Camera PWA → WebSocket (WSS khi triển khai) → FastAPI → AI inference → WebSocket result → PWA cảnh báo`; backend lưu sự kiện; admin dashboard ở giai đoạn tiếp theo.
- Chỉ thử với video ghi sẵn, mô phỏng hoặc người tham gia khi phương tiện đứng yên. Không xem MVP là thiết bị an toàn được chứng nhận. Camera/JavaScript có thể dừng khi khóa màn hình hoặc chuyển tab; luôn báo `MONITORING_UNAVAILABLE` khi không còn giám sát đáng tin cậy.
- **Không gọi nhận diện mắt nhắm là dự đoán sớm buồn ngủ**. Các nhãn/độ tin cậy chỉ có ý nghĩa sau khi được huấn luyện, hiệu chỉnh và đánh giá với dữ liệu phù hợp.
- Kết quả phải gắn `session_id`, `frame_id`, `captured_at`, `processed_at`, `model_version`; frontend bỏ kết quả hết hạn/không đúng phiên và không phát cảnh báo từ frame cũ.
- Không đưa credentials, token Telegram, video riêng tư, dữ liệu mặt hay `.env` chứa bí mật lên Git. Mặc định không lưu video thô lên server. Dữ liệu sinh trắc chỉ lưu khi có đồng ý rõ ràng, phạm vi và thời hạn lưu xác định.

### Giao thức chung MVP v0.1 (freeze trước khi tích hợp)
**WebSocket:** `/ws/monitor?session_id=<uuid>` trong môi trường phát triển có kiểm soát; trước khi đưa lên Internet phải thêm xác thực người dùng/phiên và kiểm tra quyền. Client tạo session bằng `POST /api/v1/sessions` (MVP có thể dùng một tài khoản thử nghiệm, không hardcode thông tin tài xế thực).

MVP truyền mỗi frame bằng **một message JSON** chứa JPEG base64 để dễ debug; giới hạn kích thước/fps, server giải mã an toàn. Sau MVP mới cân nhắc binary frames hoặc WebRTC. Chỉ gửi 3–5 FPS trong thử kết nối, **không tuyên bố đủ để phát hiện hành vi chớp mắt ngắn hoặc giám sát an toàn thực tế**.

Client → Server (frame):
```json
{
  "type": "frame",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "frame_id": 12,
  "captured_at": "2026-11-02T03:00:00.000Z",
  "image_format": "jpeg",
  "image_base64": "<base64-jpeg>"
}
```
Server → Client (khi chưa tích hợp AI):
```json
{
  "type": "analysis_result",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "frame_id": 12,
  "captured_at": "2026-11-02T03:00:00.000Z",
  "processed_at": "2026-11-02T03:00:00.120Z",
  "model_version": "mock-v0",
  "state": "NOT_EVALUATED",
  "alert_level": "NONE",
  "face_visible": null,
  "image_quality": "UNKNOWN",
  "risk_score": null,
  "processing_ms": 25
}
```
**Enum nhất quán:**
- `state`: `NOT_EVALUATED | NORMAL | DISTRACTED | DROWSINESS_SIGNS | CRITICAL | MONITORING_UNAVAILABLE`.
- `alert_level`: `NONE | INFO | WARNING | CRITICAL`.
- `image_quality`: `GOOD | LOW_LIGHT | BLURRY | TOO_DARK | UNKNOWN`.
- `risk_score`: `null` đến khi có mô hình đã được hiệu chỉnh; nếu có phải trong `[0,1]`, tuyệt đối không coi như xác suất đã chứng minh khi chưa calibrate.
- Trạng thái `MONITORING_UNAVAILABLE` phải đi kèm **lý do kỹ thuật** như `camera_denied`, `camera_stopped`, `network_lost`, `stale_result`, `server_error` trong thông báo trạng thái riêng, không đánh đồng với buồn ngủ.
- Giờ dùng ISO 8601 UTC; mọi sự kiện có ID bất biến; backend không tin metadata định danh người lái do client tự khai khi triển khai thật.

**Hợp đồng Python nội bộ AI ↔ Backend:**
```python
# Interface minh họa, AI và Backend chốt kiểu cụ thể cùng nhau
async def analyze_frame(frame_bgr, *, session_id: str, frame_id: int, captured_at: str) -> dict:
    # trả các trường: state, alert_level, face_visible,
    # image_quality, risk_score, model_version
    ...
```
**Phân quyền làm việc:** TV1 sở hữu `ai/`, TV2 sở hữu `frontend/`, TV3 sở hữu `backend/` và `database/`. Thay đổi API/enum phải qua `docs/api-contract.md` và cả nhóm thống nhất trước. Nhánh làm việc `feature/ai-model`, `feature/frontend`, `feature/backend`; không tự sửa code vùng người khác khi chưa trao đổi.

## Prompt bắt đầu cho Codex (TV3)
Hãy đọc `BACKEND_CONTEXT.md` và `docs/api-contract.md` (nếu có). Chỉ triển khai B1: FastAPI `/health`, tạo session thử nghiệm, WS nhận frame JPEG base64 với validation và trả mock `NOT_EVALUATED`. Viết tests cho payload lỗi, session không hợp lệ, disconnect, frame trễ; ghi hướng dẫn chạy. Chưa thêm AI model, database production, Telegram hoặc auth production; ghi rõ các rủi ro trước khi đưa endpoint lên Internet.
