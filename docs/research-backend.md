# Nghiên cứu Kỹ thuật & Pháp lý — Backend M3 (PreDrive AI)

Tài liệu này tổng hợp kết quả nghiên cứu cho 6 bài toán kiến trúc, kỹ thuật và pháp lý của phân hệ Backend M3 (Hệ thống giám sát buồn ngủ tài xế dành cho nhà xe / đội xe có người trực).

---

## 1. SSE hay WebSocket cho luồng đẩy một chiều (Server → Web Admin)? Xác thực cho SSE

### 1.1. So sánh SSE (Server-Sent Events) và WebSocket
| Tiêu chí | Server-Sent Events (SSE) | WebSocket (WS) |
|---|---|---|
| **Chiều truyền dữ liệu** | Một chiều (Server → Client) | Hai chiều (Full-duplex) |
| **Giao thức nền** | Chuẩn HTTP/1.1 hoặc HTTP/2 thuần túy (`text/event-stream`) | Cần bước bắt tay nâng cấp (`HTTP 101 Switching Protocols`) |
| **Tự động kết nối lại** | Có sẵn trong chuẩn (`EventSource` + `Last-Event-ID`) | Phải tự cài đặt ở tầng ứng dụng |
| **Tương thích hạ tầng** | Đi qua Reverse Proxy, Load Balancer, Firewall chuẩn HTTP dễ dàng | Dễ bị ngắt bởi proxy nếu cấu hình thiếu header `Upgrade` |
| **Độ phù hợp với Web Admin** | **Rất cao:** Web Admin chỉ nhận luồng trạng thái (`driver_state`) và cảnh báo (`alert`), còn thao tác "Đã liên hệ" (`ack`) thực hiện qua REST `POST /api/v1/events/{id}/ack`. | Thừa khả năng hai chiều không cần thiết cho màn hình trực ban. |

**Kết luận:** Chọn **SSE (`GET /api/v1/live/stream`)** cho luồng đẩy thời gian thực từ Server xuống Web Admin.

### 1.2. Bài toán xác thực khi `EventSource` thuần của trình duyệt không gửi được Header `Authorization`
API `new EventSource(url)` mặc định của trình duyệt không cho phép truyền custom headers (`Authorization: Bearer <jwt>`). So sánh 3 phương án giải quyết:

1. **Phương án A — Thư viện `@microsoft/fetch-event-source` (dựa trên Fetch API + ReadableStream):**
   - *Ưu điểm:* Gửi được trực tiếp header `Authorization: Bearer <jwt>` đồng nhất 100% với mọi endpoint REST khác; không làm lộ token trên URL; kiểm soát chiến lược retry và xử lý lỗi HTTP (`401`, `403`) rõ ràng.
   - *Nhược điểm:* Web Admin cần cài thêm 1 package nhỏ (~3 KB).
2. **Phương án B — Cookie `HttpOnly` (`SameSite=Lax/Strict`, `Secure`):**
   - *Ưu điểm:* Trình duyệt tự động đính kèm cookie khi mở `EventSource(..., { withCredentials: true })`; chống đánh cắp token qua XSS.
   - *Nhược điểm:* Phức tạp khi triển khai khác tên miền/cổng (cross-origin CORS credentials) và đòi hỏi cơ chế chống CSRF cho các endpoint ghi.
3. **Phương án C — Truyền JWT qua Query Parameter (`?token=<jwt>` hoặc short-lived ticket):**
   - *Ưu điểm:* Dùng được ngay với `new EventSource()` thuần mà không cần thư viện ngoài.
   - *Nhược điểm:* Token có nguy cơ xuất hiện trong access log của proxy/server hoặc lịch sử trình duyệt nếu dùng token dài hạn.

**Quyết định triển khai:**
- **Phương án chính thức:** Sử dụng header **`Authorization: Bearer <jwt>`** (tương thích với `curl -N -H "Authorization: Bearer ..."` và `@microsoft/fetch-event-source` trên Web Admin).
- **Hỗ trợ bổ sung cho Dev/Native EventSource:** Endpoint `/api/v1/live/stream` chấp nhận thêm query param tùy chọn `?token=<jwt>` như phương án dự phòng tiện lợi khi thử nghiệm nhanh trên trình duyệt.

---

## 2. Thiết kế Idempotency cho Upsert Sự kiện (`events` & `events/batch`)

Khi xe di chuyển qua vùng sóng yếu (đèo, hầm, quốc lộ), ứng dụng tài xế có thể gửi lại cùng một sự kiện nhiều lần hoặc các bản cập nhật trạng thái (`OPEN`, `ESCALATED`, `CLOSED`) đến server không đúng thứ tự thời gian.

### 2.1. Khóa duy nhất (Unique Key)
- `eventId` là UUID do App Tài xế sinh ra ngay khi bắt đầu phát hiện sự kiện và giữ cố định trong suốt vòng đời sự kiện đó.
- Trong cơ sở dữ liệu, cột `events.id` là **Khóa chính (`PRIMARY KEY`)** kiêm khóa duy nhất.
- Tương tự, `sessions.id` nhận `sessionId` từ App Tài xế làm `PRIMARY KEY` để việc gọi `POST /api/v1/sessions` nhiều lần là hoàn toàn idempotent.

### 2.2. Quy tắc chuyển trạng thái đơn điệu (Monotonic Merge Rules)
Khi một `eventId` đã tồn tại trong DB, hệ thống không ghi đè mù quáng mà hợp nhất theo quy tắc **chỉ tiến không lùi**:
- **Mức độ cảnh báo (`level`):** Thứ tự ưu tiên `WARNING (1) < CRITICAL (2)`.
  $$\text{level}_{\text{mới}} = \max(\text{level}_{\text{cũ}}, \text{level}_{\text{đến}})$$
- **Trạng thái vòng đời (`status`):** Thứ tự ưu tiên `OPEN (1) < ESCALATED (2) < CLOSED (3)`.
  $$\text{status}_{\text{mới}} = \max(\text{status}_{\text{cũ}}, \text{status}_{\text{đến}})$$
- **Thời lượng & Điểm rủi ro:**
  - `durationSec = max(existing.duration_sec, incoming.duration_sec)`
  - `riskScore = max(existing.risk_score, incoming.risk_score)` (bỏ qua `null`)
  - `startedAt = min(existing.started_at, incoming.started_at)`
  - `capturedAt = max(existing.captured_at, incoming.captured_at)`

Nhờ quy tắc này, dù gói tin `CLOSED` đến trước gói tin `OPEN` hay `ESCALATED`, bản ghi cuối cùng vẫn hội tụ chính xác về trạng thái cao nhất mà sự kiện từng đạt tới (`level = CRITICAL`, `status = CLOSED`).

### 2.3. Xử lý Race Condition khi 2 Request cùng `eventId` đến đồng thời
- Thực thi thao tác Upsert bên trong transaction với cơ chế bắt `IntegrityError` (hoặc khóa dòng/bảng trong giao dịch ghi):
  1. Kiểm tra bản ghi theo `eventId`.
  2. Nếu chưa có $\rightarrow$ `INSERT` trong savepoint (`begin_nested()`).
  3. Nếu một request song song vừa `INSERT` trước gây `IntegrityError` $\rightarrow$ rollback savepoint, truy vấn lại bản ghi vừa được chèn và áp dụng hàm hợp nhất đơn điệu (`merge_event_monotonic`).

---

## 3. Đánh giá SQLite WAL cho Nhiều Kết nối Ghi (Heartbeat) & Khi nào chuyển PostgreSQL

### 3.1. Khả năng của SQLite ở chế độ WAL (`Write-Ahead Logging`)
Khi kích hoạt:
```sql
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;
PRAGMA busy_timeout=5000;
PRAGMA foreign_keys=ON;
```
- **Cơ chế:** Dữ liệu ghi được nối vào file `-wal` tuần tự thay vì ghi đè trực tiếp vào file DB chính. Các luồng đọc (`GET /live`, `GET /events`, `GET /stats`) hoàn toàn **không bị chặn** bởi luồng ghi (`POST /heartbeat`), và ngược lại.
- **Tải thực tế của bài toán:**
  - Giả sử 100 tài xế đang chạy đồng thời, chu kỳ `heartbeatIntervalSec = 30s` $\rightarrow$ trung bình chỉ có **~3.3 lượt ghi/giây**.
  - SQLite WAL trên ổ SSD tiêu chuẩn xử lý tốt **300 – 1.000+ giao dịch ghi ngắn/giây** với `busy_timeout = 5000ms` để tự động xếp hàng các kết nối ghi trùng thời điểm.
- **Kết luận:** SQLite WAL **hoàn toàn đủ và rất mượt** cho môi trường phát triển, demo và triển khai quy mô một máy chủ (Single-node) lên tới vài trăm xe.

### 3.2. Khi nào cần chuyển sang PostgreSQL?
Hệ thống được thiết kế sẵn để chuyển sang PostgreSQL chỉ bằng biến môi trường `DATABASE_URL=postgresql+psycopg://...` khi gặp một trong các điều kiện sau:
1. **Triển khai đa tiến trình / đa máy chủ (Horizontal Scaling / Containers):** SQLite dựa trên khóa file cục bộ của hệ điều hành, không dùng chung qua mạng giữa nhiều container độc lập.
2. **Quy mô lớn (> 500–1.000 xe hoạt động liên tục):** Cần cơ chế **Row-level locking** thực sự của PostgreSQL thay vì khóa tuần tự một writer của SQLite.
3. **Vận hành Production Cloud:** Cần sao lưu liên tục (Point-in-Time Recovery), High Availability (Primary-Replica) và phân vùng bảng (`Partitioning`) cho bảng `events` / `heartbeats`.

---

## 4. Xử lý Múi giờ: Lưu trữ UTC và Gom nhóm Thống kê theo Giờ Việt Nam (`Asia/Ho_Chi_Minh`)

### 4.1. Nguyên tắc lưu trữ và truyền tải
- Toàn bộ thời gian trong cơ sở dữ liệu và giao tiếp JSON đều dùng chuẩn **UTC (ISO 8601 có hậu tố `Z`)**, ví dụ: `"2026-11-09T19:30:00Z"`.
- Việc lưu UTC giúp tránh mọi sự mơ hồ khi so sánh khoảng thời gian (`receivedAt - capturedAt > 60s`), tính timeout mất kết nối hoặc đồng bộ giữa nhiều thiết bị.

### 4.2. Gom nhóm thống kê theo giờ địa phương (`Asia/Ho_Chi_Minh`, UTC+07:00)
- Các báo cáo `/api/v1/stats/hourly` và `/api/v1/drivers/{id}/stats` phục vụ quản lý nhà xe tại Việt Nam nhằm nhận diện khung giờ tài xế hay buồn ngủ nhất (thường rơi vào **02:00 – 04:00 sáng giờ Việt Nam**).
- Nếu trích xuất `hour` trực tiếp từ giờ UTC, khung `02:00 – 04:00 sáng VN` sẽ bị hiểu nhầm thành `19:00 – 21:00 tối hôm trước`!
- **Giải pháp:** Trước khi tính thống kê theo khung giờ `0..23`, mọi mốc `started_at` của sự kiện được quy đổi từ UTC sang múi giờ `Asia/Ho_Chi_Minh` (`UTC + 7 giờ` thông qua `zoneinfo.ZoneInfo("Asia/Ho_Chi_Minh")`), đảm bảo biểu đồ 24 giờ phản ánh đúng giờ sinh học thực tế tại Việt Nam.

---

## 5. Chính sách Lưu trữ & Bảo vệ Dữ liệu Cá nhân (Nghị định 13/2023/NĐ-CP & Luật BVDLCN 2025)

### 5.1. Căn cứ pháp lý hiện hành tại Việt Nam
1. **Nghị định số 13/2023/NĐ-CP** ngày 17/04/2023 của Chính phủ về Bảo vệ dữ liệu cá nhân (hiệu lực từ 01/07/2023).
2. **Luật Bảo vệ dữ liệu cá nhân năm 2025 (Luật số 91/2025/QH15)** được Quốc hội thông qua ngày 26/06/2025 (hiệu lực từ 01/01/2026).

Theo **Khoản 4 Điều 2 Nghị định 13/2023/NĐ-CP** và **Luật BVDLCN 2025**:
- **Dữ liệu sinh trắc học** (hình ảnh/đặc trưng khuôn mặt) và **Dữ liệu vị trí của cá nhân** (tọa độ GPS) được phân loại là **Dữ liệu cá nhân nhạy cảm**.
- Việc xử lý dữ liệu nhạy cảm bắt buộc phải: (1) Thông báo rõ mục đích, (2) Có sự đồng ý rõ ràng và tự nguyện của chủ thể dữ liệu, (3) Áp dụng biện pháp tối thiểu hóa dữ liệu và giới hạn thời gian lưu trữ.

### 5.2. Chính sách thiết kế trong PreDrive AI
1. **Tuyệt đối không thu thập/lưu trữ hình ảnh hoặc video khuôn mặt trên máy chủ:**
   - Quá trình phân tích khuôn mặt diễn ra 100% trên thiết bị của tài xế (On-Device AI).
   - Máy chủ chỉ nhận các chỉ số trạng thái trừu tượng (`state`, `imageQuality`, `riskScore`, `durationSec`).
2. **Cơ chế Đồng ý minh bạch (`consentedAt`):**
   - Khi tài xế ghép nối vào tổ chức/phương tiện qua endpoint `POST /api/v1/auth/pair`, hệ thống lưu dấu thời gian đồng ý (`consented_at`) trong bảng `pairings`.
3. **Vị trí là tùy chọn (`shareLocation = false` mặc định):**
   - Mặc định hệ thống **không lưu** tọa độ GPS. Chỉ khi tổ chức bật rõ ràng `shareLocation = true` trong `Settings` và tài xế gửi kèm tọa độ thì vị trí mới được ghi nhận.
4. **Chính sách thời hạn lưu trữ và tự động dọn dẹp (Data Retention):**
   - **Dữ liệu `heartbeats` và `locations`:** Chỉ giữ lại trong **7 ngày** (cấu hình qua biến môi trường `PREDRIVE_HEARTBEAT_RETENTION_DAYS=7`). Tác vụ nền định kỳ tự động xóa các bản ghi quá hạn để giảm dung lượng và bảo vệ quyền riêng tư.
   - **Dữ liệu `sessions` và `events`:** Lưu trữ phục vụ đối soát an toàn giao thông trong **90 – 365 ngày** theo quy định nội bộ của đơn vị vận tải.

---

## 6. Quy định Pháp luật Việt Nam về Thời gian Lái xe & Đề xuất Ngưỡng Cảnh báo

### 6.1. Văn bản pháp luật hiện hành
1. **Khoản 1 Điều 64 Luật Trật tự, an toàn giao thông đường bộ năm 2024 (Luật số 36/2024/QH15)** — có hiệu lực từ ngày **01/01/2025** (thay thế Luật Giao thông đường bộ 2008):
   > *"Thời gian lái xe của người lái xe ô tô không quá 10 giờ trong một ngày và không quá 48 giờ trong một tuần; **lái xe liên tục không quá 04 giờ** và bảo đảm các quy định có liên quan của Bộ luật Lao động."*
2. **Nghị định 168/2024/NĐ-CP** quy định xử phạt vi phạm hành chính về trật tự, an toàn giao thông đường bộ: Xử phạt nghiêm hành vi điều khiển xe ô tô kinh doanh vận tải quá thời gian quy định tại Điều 64 Luật TTATGTĐB.
3. **Quy chuẩn kỹ thuật quốc gia QCVN 31:2014/BGTVT** (về thiết bị giám sát hành trình của xe ô tô): Quy định người lái xe phải dừng nghỉ tối thiểu **15 phút** để được tính là kết thúc một đợt lái xe liên tục.

### 6.2. Đề xuất giá trị mặc định cho `Settings`
Mặc dù trần pháp lý tối đa cho một lần lái xe liên tục là **4 giờ (`14.400 giây`)**, mục tiêu của PreDrive AI là **phòng ngừa sớm sự mệt mỏi và buồn ngủ trước khi tài xế kiệt sức hoặc vi phạm luật**. Do đó, hệ thống thiết lập bộ tham số mặc định theo Hợp đồng API:

| Tham số | Giá trị mặc định | Quy đổi | Ý nghĩa nghiệp vụ & Pháp lý |
|---|---|---|---|
| `continuousWarnSec` | **`7200`** | **2 giờ** | Cảnh báo nhắc nhở sớm (`WARNING`) khi tài xế đã lái liên tục nửa chặng giới hạn luật định, khuyến khích dừng nghỉ ngắn. |
| `continuousCriticalSec` | **`10800`** | **3 giờ** | Cảnh báo nghiêm trọng (`CRITICAL`) trước mốc giới hạn pháp lý 4 giờ (`14400s`) đúng 1 tiếng để người trực (`dispatcher`) kịp thời liên hệ nhắc tài xế vào trạm dừng nghỉ. *(Quản lý có thể điều chỉnh lên tới `14400s` tùy tuyến đường)*. |
| `restResetMin` | **`15`** | **15 phút** | Thời gian xe dừng nghỉ tối thiểu để reset bộ đếm lái xe liên tục, tuân thủ đúng chuẩn **15 phút** của Bộ GTVT (QCVN 31:2014/BGTVT). |
| `heartbeatIntervalSec` | **`30`** | **30 giây** | Chu kỳ gửi nhịp tim từ App Tài xế; nếu quá `2 × 30 = 60 giây` không có tín hiệu khi phiên đang mở sẽ chuyển sang `DISCONNECTED`. |
| `shareLocation` | **`false`** | Tắt | Tuân thủ nguyên tắc bảo vệ dữ liệu cá nhân mặc định (Privacy by Default) theo Nghị định 13/2023/NĐ-CP. |

---

## Tài liệu Tham khảo
1. Quốc hội nước CHXHCN Việt Nam (2024), *Luật Trật tự, an toàn giao thông đường bộ số 36/2024/QH15*, Điều 64.
2. Chính phủ nước CHXHCN Việt Nam (2023), *Nghị định số 13/2023/NĐ-CP về Bảo vệ dữ liệu cá nhân*, Điều 2, Điều 9, Điều 11.
3. Quốc hội nước CHXHCN Việt Nam (2025), *Luật Bảo vệ dữ liệu cá nhân số 91/2025/QH15*.
4. Bộ Giao thông Vận tải (2014), *Quy chuẩn kỹ thuật quốc gia QCVN 31:2014/BGTVT về thiết bị giám sát hành trình của xe ô tô*.
5. WHATWG HTML Living Standard — *Server-Sent Events (`EventSource`)* & SQLite Documentation — *Write-Ahead Logging (WAL)*.

