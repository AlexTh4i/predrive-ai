# PreDrive AI: Phiếu giao việc cho Antigravity (Production Hardening v1)

> Cách dùng: dán **mục 0 → 3** vào đầu mỗi phiên làm việc, sau đó dán **một Phase** (mục 4) mỗi lần. Không giao nhiều Phase cùng lúc.

---

## 0. Vai trò và mục tiêu

Bạn là kỹ sư phần mềm chính của dự án **PreDrive AI** (giám sát buồn ngủ/mất tập trung cho tài xế đường dài + điều hành đội xe).
Mục tiêu đợt này: đưa hệ thống từ mức demo (SQLite, seed, SSE trong bộ nhớ) lên mức **chạy được cho pilot nhiều công ty**: PostgreSQL trên Supabase, bảo mật, hạ tầng, giám sát và các tính năng nghiệp vụ vận tải.

Đọc trước: `PROJECT_CONTEXT.md` (v3.0), `backend/app/models/models.py`, `backend/app/core/security.py`, `backend/app/services/*.py`, `supabase/schema.sql`, `supabase/seed.sql`.

## 1. Quy tắc bắt buộc (không được vi phạm)

| # | Quy tắc |
|---|---|
| R1 | **Không bao giờ** truyền/lưu ảnh hoặc video khuôn mặt về server. Chỉ metadata sự kiện + heartbeat. |
| R2 | Giữ xanh: 18/18 pytest, Playwright của `admin-web/`, build `frontend/`. Không xóa/skip test để qua. |
| R3 | Mọi ngưỡng/thời gian đọc từ bảng `settings` (theo công ty), không hard-code. |
| R4 | **Không commit bí mật**: `.env`, mật khẩu DB, JWT secret, FCM key. Chỉ commit `.env.example`. |
| R5 | `ENV=production` thì: không seed, không tài khoản mặc định, không bật Swagger công khai, CORS chỉ domain thật. |
| R6 | Mọi truy vấn dữ liệu nghiệp vụ **phải lọc theo `organization_id` của người dùng** (xem Phase 1). |
| R7 | Mỗi task: nhánh `feat/<ID>`, commit nhỏ, cập nhật `PROJECT_CONTEXT.md`. |
| R8 | Không tự ý đổi hợp đồng API đang dùng bởi `frontend/` và `admin-web/`; nếu bắt buộc, giữ tương thích ngược hoặc sửa cả hai phía. |
| R9 | Không chắc thì hỏi; không đoán. Việc không làm được (cần tài khoản, khóa API, domain) thì ghi rõ vào báo cáo, không giả lập. |

## 2. Đầu vào người dùng sẽ cung cấp (agent không tự bịa)

- `SUPABASE_DB_URL` (chuỗi kết nối Postgres của Supabase) qua biến môi trường.
- Tên miền thật + IP máy chủ (hoặc nền tảng deploy).
- Khóa dịch vụ: Sentry DSN, Firebase (FCM), Zalo OA/ZNS hoặc SMS provider (nếu có).

Thiếu mục nào thì làm phần không phụ thuộc, đánh dấu `BLOCKED: cần <mục>` trong báo cáo.

## 3. Hiện trạng đã có sẵn (do người dùng cung cấp)

- `supabase/schema.sql`: 22 bảng, enum, RLS, view `v_events_pending_escalation`, `v_driver_usage_7d`, hàm `nearest_rest_stops()`, `purge_old_data()` (+ lịch pg_cron).
- `supabase/seed.sql`: ~20 dòng mỗi bảng, 3 công ty, mật khẩu `'!UNSET'` (chạy `scripts/hash_seed_passwords.py` để đặt mật khẩu dev).
- `scripts/push_to_supabase.sh`, `scripts/backup.sh`, `scripts/hash_seed_passwords.py`.
- **Lưu ý:** hai file SQL được viết nhưng **chưa được chạy thử trên Postgres thật**. Việc đầu tiên là kiểm chứng (P0-1).

---

## 4. Các Phase (mỗi lần giao một Phase)

### Phase 0: Cơ sở dữ liệu PostgreSQL + Supabase

| ID | Việc | DoD |
|---|---|---|
| P0-1 | Chạy `schema.sql` rồi `seed.sql` trên Postgres 15 sạch (Docker local), sửa lỗi cú pháp nếu có | Cả hai chạy không lỗi; truy vấn đếm trả đúng ~20 dòng/bảng |
| P0-2 | Đối chiếu `models.py` (SQLAlchemy) với `schema.sql`; cập nhật models + **Alembic migration** để khớp (kiểu id UUID, enum, cột mới, bảng mới) | `alembic upgrade head` trên DB trống tạo ra schema tương đương `schema.sql`; không còn lệch |
| P0-3 | Cấu hình `DATABASE_URL` hỗ trợ cả SQLite (dev) và Postgres (prod); dùng pool phù hợp Supabase (pooler/`sslmode=require`) | Toàn bộ pytest xanh trên **cả hai** DB |
| P0-4 | Viết lại `seed.py` của backend để dùng dữ liệu tương đương `seed.sql`, chỉ chạy khi `ENV != production` | Khởi động ở production không tạo user nào |
| P0-5 | Đẩy lên Supabase bằng `scripts/push_to_supabase.sh` (người dùng cấp URL) | `select count(*)` từng bảng đúng; RLS bật trên mọi bảng (kiểm bằng `pg_tables.rowsecurity`) |

### Phase 1: Bảo mật và multi-tenant

| ID | Việc | DoD |
|---|---|---|
| P1-1 | **Xóa tài khoản/mật khẩu seed ở production** (xem R5); bắt buộc đổi mật khẩu lần đầu cho user tạo bởi manager | Test: `ENV=production` → bảng `users` rỗng sau khởi động, không có `manager123` |
| P1-2 | **Access token ngắn (15 phút) + refresh token xoay vòng**, lưu **hash** vào `refresh_tokens`, thu hồi khi đăng xuất/đổi mật khẩu, phát hiện tái sử dụng token cũ | Test: dùng lại refresh token đã xoay → thu hồi cả chuỗi; app và admin-web tự refresh |
| P1-3 | **Rate limit**: đăng nhập (chặt, theo IP + username), ghép xe, `/events/batch`, `/heartbeat` (theo thiết bị) | Test: vượt ngưỡng → HTTP 429 kèm `Retry-After`; backend dùng Redis nếu có, in-memory nếu không |
| P1-4 | **Audit log** ghi vào `audit_logs`: đăng nhập (thành công/thất bại), ack sự kiện, sửa settings, tạo tài xế/mã ghép, tạo/thu hồi API key, xuất báo cáo | Mỗi hành động trên có đúng 1 dòng; manager xem được qua API có phân trang |
| P1-5 | **Multi-tenant thật**: mọi query lọc theo `organization_id` rút từ JWT; không nhận `organization_id` từ client; SSE chỉ phát cho đúng công ty | Test: user công ty A gọi mọi endpoint không thấy/không sửa được dữ liệu công ty B (kể cả đoán UUID, SSE, báo cáo) |
| P1-6 | Siết cấu hình: tắt `/docs` ở production, CORS theo `CORS_ORIGINS`, security headers, giới hạn kích thước body | Test cấu hình production |
| P1-7 | Quản lý `consents` (Nghị định 13/2023): app hiển thị đồng ý, lưu phiên bản + thời điểm; chưa đồng ý thì app **không gửi** dữ liệu | Test: không có consent → server từ chối nhận heartbeat/event |

### Phase 2: Hạ tầng, giám sát, sao lưu

| ID | Việc | DoD |
|---|---|---|
| P2-1 | `backend/Dockerfile`, `admin-web/Dockerfile` (build tĩnh + nginx), `docker-compose.yml` gồm backend, admin-web, redis, caddy, prometheus, grafana; Postgres local qua profile `local` | `docker compose up` một lệnh chạy toàn bộ; healthcheck mỗi service |
| P2-2 | **HTTPS + domain**: Caddy reverse proxy tự cấp Let's Encrypt; `/api/*` → backend (tắt buffering cho SSE: `flush_interval -1`), còn lại → admin-web; Grafana ở subdomain | Truy cập `https://<DOMAIN>` hợp lệ; SSE hoạt động qua proxy; app Android gọi được qua HTTPS |
| P2-3 | **CI/CD** `.github/workflows/ci.yml`: backend pytest trên service Postgres 15, **áp `schema.sql` để kiểm tra**, build `frontend/` + `admin-web/`, Playwright; CD: build image, đẩy registry, deploy khi merge `main` | CI xanh trên PR; deploy tự động có bước rollback |
| P2-4 | **Giám sát**: `/metrics` Prometheus (số phiên active, sự kiện/giờ, độ trễ API, số tài xế `DISCONNECTED`, độ trễ SSE), dashboard Grafana, **Sentry** cho backend + admin-web + app; cảnh báo khi API lỗi/DB đứt/không còn heartbeat | Dashboard có sẵn dạng file provisioning; Sentry nhận lỗi thử |
| P2-5 | **Sao lưu**: cron chạy `scripts/backup.sh`, đồng bộ ra nơi lưu ngoài máy (S3/Backblaze/…); tài liệu khôi phục; **drill khôi phục** vào DB tạm | Có log một lần khôi phục thành công; tài liệu `docs/backup-restore.md` |
| P2-6 | **Retention**: đảm bảo `purge_old_data()` chạy hằng ngày (pg_cron hoặc job nền của backend); trang `/settings` cho manager sửa số ngày lưu | Test: dữ liệu quá hạn bị xóa, dữ liệu mới giữ nguyên; log số dòng đã xóa |
| P2-7 | **Redis pub/sub cho SSE** (`sse.py`) để chạy nhiều instance backend | Test 2 instance: sự kiện từ instance A tới client nối instance B |

### Phase 3: Tính năng nghiệp vụ

| ID | Việc | DoD |
|---|---|---|
| P3-1 | **GPS + bản đồ**: app gửi vị trí (tần suất cấu hình để tiết kiệm pin) vào `locations`; trang bản đồ trong `admin-web` (Leaflet + OSM, không cần khóa) hiển thị vị trí xe trực tiếp, tốc độ, vệt hành trình; cảnh báo gắn `event_id` hiện trên bản đồ | Xe di chuyển trên bản đồ theo thời gian thực; bấm cảnh báo thấy đúng điểm trên tuyến |
| P3-2 | **Giờ lái liên tục và nghỉ**: tính từ `sessions`/`rest_breaks` theo `max_continuous_drive_min`, `min_rest_min`, `rest_reminder_before_min`; nhắc trên app + báo điều hành; **gợi ý điểm dừng gần nhất** bằng `nearest_rest_stops()` | Test: đúng thời điểm nhắc; điểm gợi ý đúng thứ tự khoảng cách |
| P3-3 | **Cảnh báo nhiều mức** (1 nhắc nhẹ → 2 chuông → 3 báo điều hành) theo `level1_sec/level2_sec/level3_sec`; app + backend đồng bộ `level` | Mỗi mức hành xử khác nhau; thay ngưỡng trong settings có hiệu lực không cần build lại app |
| P3-4 | **Đo nhờn cảnh báo / bỏ dùng app**: app ghi `app_usage_daily` (số lần tắt giám sát, cảnh báo sai); nút "Báo sai/đúng" trên mỗi cảnh báo → `events.driver_feedback`; trang quản lý hiển thị `v_driver_usage_7d` | Có biểu đồ tỉ lệ tắt giám sát/giờ và % cảnh báo sai theo tài xế |
| P3-5 | **Leo thang tự động** trong `watchdog.py` dựa trên `v_events_pending_escalation` + `escalation_policies`: quá `ack_timeout_sec` chưa "Đã liên hệ" → thông báo cấp trên (push → sms/zalo → gọi lại), ghi `escalations`, chuyển trạng thái `ESCALATED` | Test: không ack → leo đúng mức, đúng người, đúng thời điểm; ack rồi thì dừng; không gửi trùng |
| P3-6 | **Điểm rủi ro và báo cáo**: job tính `risk_scores` theo ca/tuần/tháng (công thức ghi trong `docs/risk-score.md`, trọng số cấu hình được); xuất **PDF/Excel** tuần/tháng cho manager, lưu `reports` | Tải được file; số liệu khớp truy vấn thủ công; chỉ manager truy cập |
| P3-7 | **Push FCM** cho dispatcher/manager (web) và tài xế (Android), dùng `push_tokens` | Nhận push khi đã đóng tab/app |
| P3-8 | **Tích hợp bên thu ba**: API công khai theo `api_keys` (chỉ lưu hash, scope, thu hồi được) + **webhook** có chữ ký HMAC khi có `alert.created`/`alert.escalated`, retry có backoff; nhận vị trí từ thiết bị giám sát hành trình qua `vehicles.tracker_device_id` | OpenAPI rõ ràng; test chữ ký webhook; khóa bị thu hồi thì bị từ chối |
| P3-9 | Thông báo tự động Zalo OA/ZNS hoặc SMS (`notify.py`) với fallback khi lỗi | Có provider mock cho test; provider thật `BLOCKED` nếu chưa có khóa |

---

## 5. Thứ tự thực hiện

`P0 → P1 → P2 → P3-1 → P3-3 → P3-5 → P3-2 → P3-4 → P3-7 → P3-6 → P3-8 → P3-9`

Lý do: có DB thật và bảo mật trước, rồi hạ tầng, sau đó mới thêm tính năng. **Không bắt đầu Phase 3 khi P1-5 (multi-tenant) chưa có test xanh.**

## 6. Mẫu lệnh giao cho từng phiên

```
Đọc ANTIGRAVITY_BRIEF.md mục 0-3 và PROJECT_CONTEXT.md.
Thực hiện Phase <X>, theo đúng thứ tự ID trong bảng.
Trước khi code: lập kế hoạch ngắn, liệt kê file sẽ sửa/tạo, nêu rủi ro.
Làm xong từng ID: chạy test, commit trên nhánh feat/<ID>.
Dừng và hỏi nếu gặp mục BLOCKED hoặc cần đổi hợp đồng API.
```

## 7. Mẫu báo cáo cuối mỗi Phase (bắt buộc)

```
Phase / ID đã xong:
File đã tạo/sửa:
Kết quả test (pytest, Playwright, build):  X/Y xanh
DoD đạt / chưa đạt (từng ID):
Mục BLOCKED (cần gì từ người dùng):
Rủi ro còn lại / việc tồn đọng:
Lệnh để người dùng tự kiểm chứng:
```

## 8. Ngoài phạm vi đợt này

Huấn luyện/đánh giá lại mô hình AI (M5, M6), iOS, camera hồng ngoại. Đây là việc riêng, xem bảng A1-A7 trong `ROADMAP`.
