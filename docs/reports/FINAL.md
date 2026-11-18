# Báo Cáo Tổng Hợp Đợt Nâng Cấp Production Hardening v1 — PreDrive AI (`FINAL.md`)

> **Nhánh tích hợp chính:** `hardening` (mỗi ID phát triển độc lập trên nhánh `feat/<ID>`, vượt cổng chất lượng rồi merge `--no-ff` vào `hardening`).  
> **Kết quả kiểm thử cuối cùng:** **`47/47` pytest xanh** · **`7/7` Playwright E2E `admin-web` xanh** · **`oxlint` `0` lỗi / `0` cảnh báo** · **Build `frontend/` & `admin-web/` xanh 100%** · **`0` ID FAILED**.

---

## 1. Tổng hợp những hạng mục đã hoàn thành (`28/28` ID qua 4 Phase)

### Phase 0 — Cơ sở dữ liệu PostgreSQL 15 + Supabase (`docs/reports/phase-0.md`)
- **`P0-1`**: Kiểm chứng & chuẩn hóa `supabase/schema.sql` (22 bảng, 5 kiểu Enum, RLS `rowsecurity = true` trên 22/22 bảng, 2 Views `v_events_pending_escalation`, `v_driver_usage_7d`, 3 hàm `current_org_id()`, `nearest_rest_stops()`, `purge_old_data()`) và `supabase/seed.sql` trên container PostgreSQL 15 sạch; tạo `scripts/hash_seed_passwords.py`.
- **`P0-2`**: Cập nhật toàn bộ 22 ORM models trong `backend/app/models/models.py` + Alembic migration `0002_production_schema_v1.py`, kiểm chứng không lệch cột/kiểu dữ liệu qua `information_schema.columns`.
- **`P0-3`**: Hỗ trợ song song SQLite WAL (dev) và PostgreSQL 15 / Supabase Pooler (`sslmode=require`, `prepare_threshold=None`, `NullPool` cho cổng `:6543`); toàn bộ test chạy xanh trên cả hai DB.
- **`P0-4`**: Viết lại `backend/app/services/seed.py` đa tổ chức (3 công ty, 20 user, 20 trạm dừng QL1A, chính sách leo thang, consents) và khóa cứng không tạo dữ liệu mẫu khi `ENV=production` (R5).
- **`P0-5`**: Xây dựng `scripts/push_to_supabase.sh` an toàn (`set +x` chống lộ mật khẩu, tự fallback sang Session Pooler IPv4 `aws-0-eu-west-1.pooler.supabase.com:5432`, từ chối ghi đè DB đã có dữ liệu, không chạy `seed.sql` khi `ENV=production`).

### Phase 1 — Bảo mật, Phân quyền & Cách ly Multi-tenant (`docs/reports/phase-1.md`)
- **`P1-1`**: Xóa hoàn toàn tài khoản mặc định ở production; tài xế do `manager` tạo nhận mật khẩu tạm ngẫu nhiên + `must_change_password = true`, bị chặn mọi thao tác (`403 PASSWORD_CHANGE_REQUIRED`) cho tới khi đổi mật khẩu lần đầu.
- **`P1-2`**: Access Token ngắn hạn **15 phút** + **Refresh Token xoay vòng** chỉ lưu SHA-256 `token_hash` trong `refresh_tokens` theo `family_id`; thu hồi khi logout/đổi mật khẩu, phát hiện replay thu hồi toàn chuỗi (`401 REFRESH_TOKEN_REUSED`); tự refresh trên cả `admin-web` và `frontend`.
- **`P1-3`**: `SlidingWindowRateLimiter` dùng Redis (khi có `REDIS_URL`) hoặc in-memory fallback, bảo vệ `/auth/login`, `/auth/pair`, `/events*`, `/heartbeat` bằng HTTP `429` kèm `Retry-After`.
- **`P1-4`**: Ghi `audit_logs` chính xác 1 dòng/hành động (đăng nhập thành công/thất bại, ack sự kiện, sửa settings, tạo tài xế/mã ghép, tạo/thu hồi API key, tạo/xóa webhook, xuất báo cáo) + API phân trang cho `manager`.
- **`P1-5`**: **Cách ly Multi-tenant tuyệt đối**: rút `organization_id` từ JWT đã xác thực (`get_jwt_org_id`), cô lập toàn bộ REST, đoán UUID, mã ghép xe, báo cáo và luồng SSE `/api/v1/live/stream`.
- **`P1-6`**: Khi `ENV=production`: tắt `/docs`, `/redoc`, `/openapi.json`; CORS động theo `CORS_ORIGINS`; gắn đầy đủ Security Headers (HSTS, CSP, X-Frame-Options, nosniff) và chặn body quá cỡ (`413`).
- **`P1-7`**: Tuân thủ **Nghị định 13/2023/NĐ-CP** qua bảng `consents` (khóa cứng `clip_storage_consent = false` theo R1 — tuyệt đối không lưu/truyền ảnh khuôn mặt); chưa đồng ý thì cả App lẫn Server đều từ chối nhận dữ liệu (`403 CONSENT_REQUIRED`).

### Phase 2 — Hạ tầng Container, Giám sát, Sao lưu & Mở rộng SSE (`docs/reports/phase-2.md`)
- **`P2-1`**: Tạo `.dockerignore`, `backend/Dockerfile`, `admin-web/Dockerfile` + `nginx.conf`, và `docker-compose.yml` gồm 7 service có `healthcheck` đầy đủ (`postgres` tách qua `--profile local`).
- **`P2-2`**: Tạo `infra/caddy/Caddyfile` cấp HTTPS Let's Encrypt tự động, định tuyến `/api/*` với `flush_interval -1` cho SSE, SPA fallback cho `admin-web`, và subdomain `grafana.${DOMAIN}` (đã kiểm chứng bằng `caddy validate`).
- **`P2-3`**: Thiết lập GitHub Actions `.github/workflows/ci.yml` kiểm chứng `schema.sql` trên Postgres 15, chạy pytest, build 2 app, chạy Playwright, đẩy image lên GHCR và SSH deploy kèm tự động rollback khi `/health` lỗi.
- **`P2-4`**: Endpoint `/metrics` Prometheus, bộ cảnh báo `infra/prometheus/alerts.yml`, dashboard Grafana provisioning tự động, và tích hợp Sentry SDK trên cả 3 tầng.
- **`P2-5`**: Tạo `scripts/backup.sh` (`pg_dump -Fc` + `.sha256` + đồng bộ S3/rclone + xóa bản cũ), chạy **drill khôi phục thực tế** sang DB tạm trên Postgres 15 và lưu biên bản tại `docs/backup-restore.md`.
- **`P2-6`**: Tự động xóa dữ liệu quá hạn hằng ngày theo số ngày lưu của từng công ty (`purge_expired_organization_data()` + `purge_old_data()`); bổ sung giao diện chỉnh số ngày lưu tại `/settings`.
- **`P2-7`**: Nâng cấp `SSEBroker` dùng **Redis Pub/Sub** để chạy nhiều replica backend song song (kiểm thử sự kiện từ Instance A tới đúng client nối Instance B).

### Phase 3 — Tính năng Nghiệp vụ Vận tải & Tích hợp Bên thứ ba (`docs/reports/phase-3.md`)
- **`P3-1`**: Gửi GPS chu kỳ cấu hình tiết kiệm pin, gắn tọa độ sự kiện (`event_id`), API `/locations/live` & `/locations/trail`, và trang **Bản đồ hành trình (`/map`)** dùng **Leaflet + OpenStreetMap**.
- **`P3-2`**: Tính giờ lái liên tục & kỳ nghỉ (`rest_breaks`), nhắc nghỉ đúng hạn kèm gợi ý trạm dừng gần nhất theo khoảng cách Haversine (`nearest_rest_stops()`).
- **`P3-3`**: Cảnh báo buồn ngủ 3 mức (`level1_sec` nhắc nhẹ → `level2_sec` chuông cabin → `level3_sec` báo điều hành) đồng bộ động từ `settings` xuống App không cần build lại.
- **`P3-4`**: Nút phản hồi **"Báo đúng / Báo sai"** trên App (`events.driver_feedback`), ghi `app_usage_daily`, và biểu đồ 7 ngày `v_driver_usage_7d` trên trang `/stats`.
- **`P3-5`**: Tự động leo thang cảnh báo quá hạn chưa liên hệ trong `watchdog.py` theo `escalation_policies`, dừng ngay khi `ack`, chống gửi trùng.
- **`P3-6`**: Công thức tính `risk_scores` (`docs/risk-score.md`) có trọng số cấu hình được theo ca/tuần/tháng; xuất file thật **PDF (`reportlab`)** và **Excel (`openpyxl`)** chỉ dành cho `manager`.
- **`P3-7`**: Quản lý `push_tokens`, Service Worker `firebase-messaging-sw.js` và gửi Push FCM ngầm khi đóng tab/app.
- **`P3-8`**: Public API `/api/public/v1/*` xác thực `X-API-Key` (chỉ lưu hash, kiểm tra scope, thu hồi được), nhận tọa độ hộp đen qua `vehicles.tracker_device_id`, và gửi Webhook ký HMAC-SHA256 kèm backoff retry.
- **`P3-9`**: Điều phối thông báo `notify.py` hỗ trợ Zalo OA/ZNS & SMS với fallback tự động (`zalo → sms → push`), mock provider cho test và báo `BLOCKED` rõ ràng khi thiếu khóa ở production.

---

## 2. Mục FAILED và Mục BLOCKED

### Mục FAILED
- **Không có (`0` ID FAILED).** Toàn bộ mã nguồn, migration, script vận hành và kiểm thử tự động của cả 28 ID đều đã hoàn thiện và vượt qua toàn bộ cổng chất lượng.

### Mục BLOCKED (Chờ thông tin/khóa môi trường thật từ người dùng — tuân thủ R4 & R9)
1. **`BLOCKED: cần SUPABASE_DB_URL`** — Chuỗi kết nối Postgres tới project Supabase `zpbskfqabxdhpdphqnjo` (`eu-west-1`) để chạy `scripts/push_to_supabase.sh` đẩy schema lên đám mây thật.
2. **`BLOCKED: cần tên miền thật (DOMAIN) và IP/SSH máy chủ triển khai`** — Để Caddy xin chứng chỉ HTTPS Let's Encrypt công khai và kích hoạt job CD deploy tự động trong GitHub Actions (`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`).
3. **`BLOCKED: cần SENTRY_DSN / VITE_SENTRY_DSN`** — Để đẩy log ngoại lệ thực tế lên tài khoản Sentry Cloud.
4. **`BLOCKED: cần cấu hình kho lưu trữ sao lưu ngoài máy (BACKUP_S3_URI + AWS key hoặc BACKUP_RCLONE_DEST)`** — Để cron `scripts/backup.sh` đồng bộ bản `.dump` ra S3 / Backblaze B2 / Cloudflare R2.
5. **`BLOCKED: cần khóa Firebase FCM (FCM_SERVER_KEY / FIREBASE_SERVICE_ACCOUNT_JSON & VITE_FCM_VAPID_KEY)`** — Để gửi Web Push / Android Push qua hạ tầng Firebase thật.
6. **`BLOCKED: cần khóa Zalo OA/ZNS (ZALO_OA_ACCESS_TOKEN, ZALO_ZNS_TEMPLATE_ID) hoặc SMS Gateway (SMS_API_URL, SMS_API_KEY)`** — Để gửi tin nhắn leo thang Zalo/SMS thật tới điện thoại điều hành ở môi trường production.

---

## 3. Danh sách việc người dùng cần tự thực hiện để đưa lên Production (Go-Live Checklist)

### Bước 1: Đẩy Schema lên Supabase (`zpbskfqabxdhpdphqnjo`, `eu-west-1`)
1. Vào **Supabase Dashboard → Project Settings → Database → Connection string → Session pooler** (cổng `5432`, tương thích IPv4), sao chép chuỗi kết nối.
2. Vào **Database → Extensions**, bật extension `pg_cron` (tùy chọn nhưng khuyến nghị để lịch `0 3 * * *` chạy song song với job retention của backend).
3. Mở Git Bash tại thư mục gốc repo và chạy (không lưu mật khẩu vào lịch sử lệnh hay file repo):
   ```bash
   export ENV=production
   read -rsp "Nhap SUPABASE_DB_URL: " SUPABASE_DB_URL && echo
   export SUPABASE_DB_URL
   bash scripts/push_to_supabase.sh
   ```
   *(Vì `ENV=production`, script sẽ chỉ áp `supabase/schema.sql`, bật RLS trên đủ 22 bảng và tự động bỏ qua `seed.sql`).*

### Bước 2: Trỏ Tên Miền (DNS) & Chuẩn bị Máy Chủ
1. Tạo 2 bản ghi DNS `A` trỏ về IP công khai của máy chủ Linux (Ubuntu 22.04/24.04 có cài Docker & Docker Compose v2):
   - `<DOMAIN>` (ví dụ `app.predrive.vn`) → `<IP_MAY_CHU>`
   - `grafana.<DOMAIN>` (ví dụ `grafana.predrive.vn`) → `<IP_MAY_CHU>`
2. Mở cổng tường lửa `80/tcp` và `443/tcp` trên máy chủ (đóng cổng `8000`, `6379`, `9090`, `3000` ra ngoài Internet — chỉ để Caddy điều phối).

### Bước 3: Tạo file `.env` trên Máy Chủ & Điền Khóa Dịch Vụ
Sao chép `.env.example` thành `.env` trên máy chủ (`chmod 600 .env`) và điền các giá trị thật:
- `ENV=production`
- `DOMAIN=<ten-mien-that>` và `CORS_ORIGINS=https://<ten-mien-that>`
- `DATABASE_URL=<chuoi-Supabase-Session-Pooler-co-sslmode=require>`
- `PREDRIVE_JWT_SECRET=$(openssl rand -hex 32)`
- `GRAFANA_ADMIN_PASSWORD=<mat-khau-manh>`
- Điền các khóa dịch vụ (khi đã đăng ký): `SENTRY_DSN`, `FCM_SERVER_KEY`, `VITE_FCM_VAPID_KEY`, `ZALO_OA_ACCESS_TOKEN`, `SMS_API_URL`, `SMS_API_KEY`, `BACKUP_S3_URI`.

### Bước 4: Khởi chạy Hệ thống & Tạo Tài khoản Quản lý Đầu tiên
1. Khởi chạy toàn bộ cụm dịch vụ Production:
   ```bash
   docker compose up -d --build
   docker compose ps
   ```
2. Kiểm tra HTTPS và healthcheck:
   ```bash
   curl -fsS https://<DOMAIN>/api/health || curl -fsS http://127.0.0.1:8000/health
   ```
3. Cài cron sao lưu tự động mỗi ngày lúc `02:15` sáng trên máy chủ:
   ```bash
   (crontab -l 2>/dev/null; echo "15 2 * * * SUPABASE_DB_URL='<URL>' BACKUP_S3_URI='<S3_URI>' /opt/predrive-ai/scripts/backup.sh >> /var/log/predrive-backup.log 2>&1") | crontab -
   ```
4. Cấu hình GitHub Repository Secrets (`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`, `DEPLOY_PATH`) nếu muốn kích hoạt tự động deploy + rollback khi merge vào nhánh `main`.

---

## 4. Lệnh tự kiểm chứng toàn bộ dự án tại máy cục bộ
```powershell
# 1. Kiểm thử toàn bộ 47 bài pytest (AI, Gateway, M3, Phase 0 -> Phase 3):
$env:PYTHONPATH = "$PWD;$PWD\backend"
.\.venv\Scripts\python.exe -m pytest ai/tests backend/tests -v

# 2. Build App Tài xế (PWA / Capacitor Android):
cd frontend; npm run build; cd ..

# 3. Typecheck, Lint, Build & chạy 7 bài kiểm thử E2E Playwright cho Web Admin:
cd admin-web; npm run typecheck; npm run lint; npm run build; npm test; cd ..
```
