# PREDRIVE AI — HỢP ĐỒNG API CHUNG (API CONTRACT v0.3 - MILESTONE 3)

Tài liệu này định nghĩa hợp đồng giao tiếp chuẩn giữa **Backend FastAPI (`backend/`)**, **App Tài xế Android** và **Web Admin / Trực ban**, kèm theo phần đối chiếu tương thích ngược với WebSocket Gateway của M1/M2.

---

## 1. Quy ước Chung

- **Base path:** `/api/v1`
- **Định dạng JSON:** Toàn bộ trường dùng **`camelCase`**.
- **Định dạng thời gian:** Chuẩn **ISO 8601 UTC** có hậu tố `Z` (ví dụ: `"2026-11-09T14:30:00Z"`).
  - *Múi giờ thống kê:* Dữ liệu lưu UTC nhưng các thống kê theo khung giờ trong ngày (`/api/v1/stats/hourly`, `/api/v1/drivers/{id}/stats`) được gom nhóm theo giờ Việt Nam **`Asia/Ho_Chi_Minh` (`UTC+07:00`)**.
- **Xác thực:** Header `Authorization: Bearer <jwt>`.
  - *Riêng endpoint SSE (`GET /api/v1/live/stream`):* Hỗ trợ cả header `Authorization: Bearer <jwt>` (khuyến nghị dùng với `@microsoft/fetch-event-source` hoặc `curl`) và query param dự phòng `?token=<jwt>` (dành cho `EventSource` thuần).
- **Định dạng lỗi thống nhất:**
  ```json
  {
    "error": {
      "code": "FORBIDDEN",
      "message": "Mô tả chi tiết lỗi"
    }
  }
  ```
- **Đa tổ chức (Multi-tenancy):** Mọi truy vấn đều lọc nghiêm ngặt theo `organizationId` của người dùng đăng nhập. Không bao giờ trả dữ liệu của tổ chức khác.
- **Phân quyền theo vai trò (`role`):**
  - `manager`: Quản lý tổ chức, xem toàn bộ báo cáo/trực tuyến, ghi nhận cảnh báo (`ack`), sửa cài đặt (`PUT /settings`), tạo mã ghép xe (`POST /pairing-codes`) và tạo tài khoản tài xế (`POST /drivers`).
  - `dispatcher`: Người trực ban, xem trực tuyến (`/live`, `/live/stream`), lịch sử sự kiện (`/events`), danh sách & thống kê tài xế (`/drivers`, `/stats/*`), xem cài đặt (`GET /settings`) và ghi nhận "Đã liên hệ" (`POST /events/{id}/ack`). **Không** được sửa `Settings` hay tạo tài xế/mã ghép đôi.
  - `driver`: Chỉ ghi dữ liệu phiên/sự kiện/heartbeat của chính mình và ghép xe (`POST /auth/pair`).

---

## 2. Tập Giá trị Enum Chuẩn

- `state`: `"NORMAL" | "DROWSINESS_SIGNS" | "CRITICAL" | "DISTRACTED" | "MONITORING_UNAVAILABLE" | "OFFLINE" | "DISCONNECTED"`
- `event.type`: `"DROWSINESS" | "LONG_DRIVING" | "DISCONNECTED" | "REST_CLAIM_REJECTED"`
- `event.level`: `"WARNING" | "CRITICAL"`
- `event.status`: `"OPEN" | "ESCALATED" | "CLOSED"`
- `imageQuality`: `"GOOD" | "LOW_LIGHT" | "BLURRY" | "TOO_DARK" | "UNKNOWN"`

---

## 3. Kiểu Dữ liệu Chuẩn (Schemas)

### `Driver`
```json
{
  "id": "178b5dab-4c16-5cf3-bbef-721df125a4b8",
  "fullName": "Nguyễn Văn An",
  "phone": "0901234501",
  "vehicleId": "a41115fc-f172-55ae-9e24-19f4adc9f7e6",
  "vehicleName": "51B-123.45 - Giường nằm 40 chỗ",
  "avatarUrl": null
}
```

### `LiveDriverState`
```json
{
  "driverId": "178b5dab-4c16-5cf3-bbef-721df125a4b8",
  "fullName": "Nguyễn Văn An",
  "phone": "0901234501",
  "vehicleName": "51B-123.45 - Giường nằm 40 chỗ",
  "state": "NORMAL",
  "sessionId": "fe91477b-a02c-4323-ac47-d9e303c2c0d1",
  "continuousDrivingSec": 1800,
  "totalDrivingSec": 5400,
  "drowsyCountToday": 2,
  "lastHeartbeatAt": "2026-11-09T14:30:00Z",
  "location": {
    "lat": 10.762622,
    "lng": 106.660172,
    "at": "2026-11-09T14:30:00Z"
  }
}
```
*(Trường `location` trả về `null` khi tổ chức tắt `shareLocation = false` hoặc tài xế không gửi vị trí).*

### `AlertEvent`
```json
{
  "id": "e73b849b-d76c-41d2-8c1f-e666d0402338",
  "sessionId": "fe91477b-a02c-4323-ac47-d9e303c2c0d1",
  "driverId": "178b5dab-4c16-5cf3-bbef-721df125a4b8",
  "driverName": "Nguyễn Văn An",
  "vehicleName": "51B-123.45 - Giường nằm 40 chỗ",
  "type": "DROWSINESS",
  "level": "CRITICAL",
  "status": "CLOSED",
  "state": "CRITICAL",
  "riskScore": 0.95,
  "startedAt": "2026-11-09T14:29:54Z",
  "durationSec": 6,
  "delayed": false,
  "capturedAt": "2026-11-09T14:30:00Z",
  "receivedAt": "2026-11-09T14:30:01Z",
  "ackBy": "Trần Thị Trực Ban",
  "ackAt": "2026-11-09T14:31:00Z",
  "note": "Đã gọi điện nhắc tài xế vào trạm nghỉ"
}
```

### `Session`
```json
{
  "id": "fe91477b-a02c-4323-ac47-d9e303c2c0d1",
  "driverId": "178b5dab-4c16-5cf3-bbef-721df125a4b8",
  "startedAt": "2026-11-09T12:00:00Z",
  "endedAt": "2026-11-09T16:00:00Z",
  "totalDrivingSec": 14400,
  "warningCount": 2,
  "criticalCount": 1
}
```

### `Settings`
```json
{
  "continuousWarnSec": 7200,
  "continuousCriticalSec": 10800,
  "restResetMin": 15,
  "shareLocation": false,
  "heartbeatIntervalSec": 30
}
```

---

## 4. Danh sách Endpoint Chi tiết

### 4.1. Nhóm AUTH
- `POST /api/v1/auth/login`
  - Body: `{username, password}`
  - Response: `{accessToken, user: {id, role, fullName, organizationId}}`
- `GET /api/v1/auth/me`
  - Response: `{id, role, fullName, organizationId}`
- `POST /api/v1/auth/pair` *(role: `driver`)*
  - Body: `{code}`
  - Response: `{vehicleName, organizationName}`

### 4.2. Nhóm APP TÀI XẾ *(role: `driver`)*
- `POST /api/v1/sessions`
  - Body: `{sessionId, startedAt}` *(Idempotent theo `sessionId`)*
  - Response: `{sessionId, settings: Settings}`
- `POST /api/v1/sessions/{id}/events`
  - Body: `{eventId, type, level, status, state, riskScore, startedAt, durationSec, capturedAt}`
  - Quy tắc Upsert: Idempotent theo `eventId`; `level` chỉ tăng (`WARNING -> CRITICAL`); `status` chỉ tiến (`OPEN -> ESCALATED -> CLOSED`); `delayed = (receivedAt - capturedAt) > 60s`.
  - Response: `AlertEvent`
- `POST /api/v1/sessions/{id}/events/batch`
  - Body: `{events: [...]}`
  - Response: `{items: AlertEvent[], total: int}`
- `POST /api/v1/sessions/{id}/heartbeat`
  - Body: `{state, imageQuality, continuousDrivingSec, vehicleMoving, capturedAt, location?}`
  - Response: `{status: "ok", state, receivedAt}`
- `POST /api/v1/sessions/{id}/end`
  - Body: `{endedAt, summary: {totalDrivingSec, warningCount, criticalCount, unavailableSec}}`
  - Response: `Session`

### 4.3. Nhóm WEB ADMIN & NGƯỜI TRỰC *(role: `manager` | `dispatcher`)*
- `GET /api/v1/live` → `LiveDriverState[]`
- `GET /api/v1/live/stream` → Luồng **SSE (`text/event-stream`)** phát sự kiện `driver_state` (`LiveDriverState`) và `alert` (`AlertEvent`). Không phát `alert` cho sự kiện có `delayed = true`.
- `GET /api/v1/events?driverId&from&to&level&type&acked&page&pageSize` → `{items: AlertEvent[], total}`
- `POST /api/v1/events/{id}/ack` `{note}` → `AlertEvent`
- `GET /api/v1/drivers` → `Driver[]`
- `GET /api/v1/drivers/{id}` → `Driver + {recentSessions: Session[]}`
- `GET /api/v1/drivers/{id}/stats?from&to` → `{totalDrivingSec, alertCount, alertsPerDrivingHour, hourly: [{hour, count}]}`
- `GET /api/v1/stats/hourly?from&to` → `[{hour: 0..23, warning, critical}]`
- `GET /api/v1/stats/ranking?from&to` → `[{driverId, fullName, alertsPerDrivingHour, alertCount}]`
- `GET /api/v1/stats/system-health?from&to` → `{tooDarkRate, unavailableRate, disconnectedCount}`
- `GET /api/v1/settings` → `Settings`
- `PUT /api/v1/settings` *(chỉ `manager`)* → `Settings`
- `POST /api/v1/pairing-codes` *(chỉ `manager`)* → `{code, expiresAt}`
- `POST /api/v1/drivers` *(chỉ `manager`)* → `Driver`

---

## 5. Ghi nhận Điểm Mở rộng / Tương thích Ngược (Không làm lệch Hợp đồng)

Tất cả tên trường, đường dẫn và kiểu dữ liệu của M3 **khớp 100% với Hợp đồng API chung**. Để đảm bảo tương thích ngược với M1/M2 và hỗ trợ kiểm thử tự động, có 3 điểm kỹ thuật bổ sung không gây ảnh hưởng tới schema hợp đồng:

1. **Cầu nối tương thích ngược trên `POST /api/v1/sessions` cho M1/M2 WebSocket (`test_gateway.py`):**
   - Trong M1/M2, `test_gateway.py` gọi `POST /api/v1/sessions` không đính kèm header `Authorization` và không truyền `sessionId` trong body để lấy `session_id` tạm thời cho `/ws/monitor`.
   - Khi nhận request chuẩn của M3 (có header `Authorization: Bearer <jwt>` hoặc có trường `sessionId` trong JSON body), endpoint thực thi đúng 100% hợp đồng M3. Chỉ khi request không có `Authorization` và body rỗng/không chứa `sessionId`, hệ thống mới trả phản hồi in-memory phục vụ `/ws/monitor`.
2. **Hỗ trợ thêm `?token=<jwt>` ẩn trên `GET /api/v1/live/stream`:**
   - Do `new EventSource()` mặc định của trình duyệt không gửi được header `Authorization`, bên cạnh việc hỗ trợ chuẩn `Authorization: Bearer <jwt>` (dùng với `@microsoft/fetch-event-source` hoặc `curl`), backend chấp nhận thêm query param tùy chọn `?token=<jwt>` (`include_in_schema=False`) để người làm Web có thể chọn bất kỳ cách nào thuận tiện nhất.
3. **Trường tùy chọn khi tạo tài xế (`POST /api/v1/drivers`) và tạo mã ghép đôi (`POST /api/v1/pairing-codes`):**
   - `POST /api/v1/pairing-codes` hoạt động ngay cả khi gửi body rỗng `{}` (mặc định hết hạn sau 60 phút) hoặc truyền `{vehicleId, expiresInMinutes}`.
   - `POST /api/v1/drivers` chỉ yêu cầu tối thiểu `{fullName, phone}`; các trường `username`, `password`, `vehicleId`, `vehicleName` là tùy chọn (nếu bỏ trống `username` sẽ tự lấy theo `phone`, `password` mặc định `"driver123"`).

---

## 6. Giao thức WebSocket Legacy (M1/M2 — Giữ nguyên để không phá code cũ)

- `GET /health` → `{"status":"ok","service":"predrive-backend","version":"0.1.0"}`
- `WS /ws/monitor?session_id=<UUID>` → Nhận frame từ bản PWA nghiên cứu M1/M2 trong bộ nhớ đệm (không lưu ảnh/video). Toàn bộ luồng sản phẩm M3 (App Tài xế Android ↔ Backend ↔ Web Admin) chỉ giao tiếp qua các REST + SSE endpoints ở Mục 4 và **tuyệt đối không gửi hoặc lưu ảnh/video**.
