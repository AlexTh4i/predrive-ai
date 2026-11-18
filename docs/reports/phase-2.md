# Báo cáo Phase 2 — Hạ tầng, Giám sát, Sao lưu & Mở rộng SSE

## Phase / ID đã xong
- `P2-1`: Tạo `.dockerignore`, `backend/Dockerfile`, `admin-web/Dockerfile` (multi-stage build tĩnh + Nginx SPA `admin-web/nginx.conf`), và `docker-compose.yml` gồm 7 dịch vụ (`backend`, `admin-web`, `redis`, `caddy`, `prometheus`, `grafana`, và `postgres` qua profile `local`) với `healthcheck` đầy đủ cho từng service.
- `P2-2`: Tạo cấu hình Reverse Proxy `infra/caddy/Caddyfile` tự động cấp chứng chỉ HTTPS Let's Encrypt theo `${DOMAIN}`, định tuyến `/api/*` → `backend:8000` kèm `flush_interval -1` (tắt buffering cho SSE `/api/v1/live/stream`), các đường dẫn còn lại phục vụ SPA `admin-web:80`, và tách subdomain `grafana.${DOMAIN}` cho Grafana; đã kiểm chứng cú pháp bằng `caddy:2.8-alpine caddy validate`.
- `P2-3`: Thiết lập quy trình CI/CD `.github/workflows/ci.yml`: khởi chạy service PostgreSQL 15 + Redis 7, áp trực tiếp `supabase/schema.sql` & `supabase/seed.sql` để kiểm chứng schema, chạy toàn bộ `pytest`, build `frontend/` + `admin-web/`, chạy E2E Playwright; job CD tự động đóng gói Docker image đẩy lên GHCR và triển khai qua SSH kèm kiểm tra `/health` và tự động rollback về image trước đó nếu lỗi.
- `P2-4`: Triển khai endpoint `/metrics` chuẩn Prometheus (`backend/app/services/observability.py`: phiên đang mở, sự kiện/giờ, số tài xế `DISCONNECTED`, histogram độ trễ HTTP API & độ trễ hàng đợi SSE), bộ quy tắc cảnh báo `infra/prometheus/alerts.yml` (lỗi API 5xx, mất kết nối DB, ngưng nhận heartbeat), dashboard Grafana provisioning tự động (`infra/grafana/provisioning/` & `predrive-overview.json`), và tích hợp Sentry SDK cho cả 3 tầng (`backend`, `admin-web`, `frontend`).
- `P2-5`: Xây dựng `scripts/backup.sh` (`pg_dump -Fc` nén custom format + kiểm tra `.sha256` + đồng bộ offsite S3/Backblaze qua AWS CLI hoặc `rclone` + dọn bản sao lưu quá hạn), thực hiện **drill khôi phục thực tế** bằng `pg_restore` sang cơ sở dữ liệu tạm trên Postgres 15, đối chiếu khớp số dòng và lưu biên bản tại `docs/backup-restore.md`.
- `P2-6`: Đảm bảo chính sách lưu trữ (Data Retention) chạy tự động hằng ngày qua cả `pg_cron` (`purge_old_data()`) lẫn tác vụ nền `purge_expired_organization_data()` trong `backend/app/services/watchdog.py` (ghi log chi tiết số dòng đã xóa, đồng thời sửa `disable_existing_loggers=False` trong `backend/migrations/env.py`); bổ sung giao diện chỉnh sửa số ngày lưu trữ (`heartbeatRetentionDays`, `locationRetentionDays`, `eventRetentionDays`, `auditRetentionDays`) cho `manager` tại trang `/settings`.
- `P2-7`: Nâng cấp `SSEBroker` (`backend/app/services/sse.py` & `backend/app/main.py`) tích hợp **Redis Pub/Sub** theo kênh `predrive:sse:org:<organization_id>` kèm `origin_id` chống lặp nội bộ, cho phép chạy nhiều instance backend song song mà sự kiện phát sinh ở Instance A vẫn đẩy tức thời tới trình duyệt đang nối SSE ở Instance B.

## File đã tạo/sửa
- Tạo mới:
  - `.dockerignore`
  - `backend/Dockerfile`
  - `admin-web/Dockerfile`
  - `admin-web/nginx.conf`
  - `docker-compose.yml`
  - `infra/caddy/Caddyfile`
  - `infra/prometheus/prometheus.yml`
  - `infra/prometheus/alerts.yml`
  - `infra/grafana/provisioning/datasources/prometheus.yml`
  - `infra/grafana/provisioning/dashboards/dashboards.yml`
  - `infra/grafana/dashboards/predrive-overview.json`
  - `.github/workflows/ci.yml`
  - `backend/app/services/observability.py`
  - `admin-web/src/lib/sentry.ts`
  - `frontend/src/services/sentry.ts`
  - `scripts/backup.sh`
  - `docs/backup-restore.md`
  - `backend/tests/test_p2_infra.py`
  - `docs/reports/phase-2.md`
- Đã sửa:
  - `backend/requirements.txt` (`prometheus-client`, `sentry-sdk[fastapi]`)
  - `backend/app/core/config.py`
  - `backend/app/main.py`
  - `backend/migrations/env.py`
  - `backend/app/schemas/m3.py`
  - `backend/app/services/mappers.py`
  - `backend/app/services/sse.py`
  - `backend/app/services/watchdog.py`
  - `backend/app/routers/web_admin.py`
  - `admin-web/package.json`, `admin-web/src/main.tsx`, `admin-web/src/types.ts`, `admin-web/src/pages/Settings.tsx`
  - `frontend/package.json`, `frontend/src/main.tsx`, `frontend/src/types/m3.ts`
  - `.env.example`
  - `PROJECT_CONTEXT.md`

## Kết quả test (pytest, Playwright, build)
- **Pytest (`ai/tests` + `backend/tests`, bao gồm Postgres 15, Redis 7 pub/sub 2 instance & restore drill):** `38/38 xanh` (`22.85s`)
- **Playwright (`admin-web`):** `6/6 xanh` + `npm run typecheck` & `npm run build` xanh
- **Frontend Driver App (`frontend`):** `npm run build` xanh

## DoD đạt / chưa đạt (từng ID)
- `P2-1`: **ĐẠT** — `docker-compose.yml` đủ 7 service kèm `healthcheck`, Postgres tách riêng qua `--profile local`.
- `P2-2`: **ĐẠT** (cấu hình & kiểm chứng `caddy validate`; phần cấp chứng chỉ Let's Encrypt trên Internet chờ domain thật) — `/api/*` tắt buffering (`flush_interval -1`), SPA fallback và `grafana.${DOMAIN}` đầy đủ.
- `P2-3`: **ĐẠT** (workflow hoàn chỉnh; bước SSH CD chờ thông tin máy chủ thật) — CI áp `schema.sql` trên Postgres 15, chạy pytest, build 2 app, chạy Playwright; CD có healthcheck và rollback tự động.
- `P2-4`: **ĐẠT** (code, provisioning Grafana & test capture Sentry in-memory xanh; đẩy lên Sentry Cloud chờ DSN thật) — `/metrics` xuất đủ chỉ số, cảnh báo Prometheus & dashboard Grafana nạp tự động.
- `P2-5`: **ĐẠT** (drill local trên Postgres 15 thành công; đồng bộ lên S3/Backblaze thật chờ URI & khóa lưu trữ) — `scripts/backup.sh` + biên bản drill trong `docs/backup-restore.md`.
- `P2-6`: **ĐẠT** — Dữ liệu quá hạn bị xóa, dữ liệu mới & sự kiện `OPEN` được giữ nguyên, ghi log số dòng đã xóa; `manager` chỉnh được số ngày lưu trên trang `/settings`.
- `P2-7`: **ĐẠT** — Kiểm thử thực tế 2 instance `SSEBroker` qua Redis 7 xác nhận sự kiện phát từ Instance A tới đúng client nối Instance B (và cô lập khác công ty).

## Mục BLOCKED (cần gì từ người dùng)
- `BLOCKED: cần tên miền thật (DOMAIN) và IP máy chủ triển khai` để Caddy xin chứng chỉ Let's Encrypt công khai và kích hoạt job SSH deploy trong GitHub Actions (`DEPLOY_HOST`, `DEPLOY_USER`, `DEPLOY_SSH_KEY`).
- `BLOCKED: cần khóa SENTRY_DSN (và VITE_SENTRY_DSN)` để gửi sự kiện lỗi thực tế lên tài khoản Sentry Cloud.
- `BLOCKED: cần cấu hình kho lưu trữ ngoài máy (BACKUP_S3_URI + AWS credentials hoặc BACKUP_RCLONE_DEST)` để cron `scripts/backup.sh` đẩy file `.dump` ra đám mây lưu trữ độc lập.

## Rủi ro còn lại / việc tồn đọng
- Khi chạy nhiều replica backend ở production (`docker compose up --scale backend=2`), tác vụ nền định kỳ (`watchdog_loop`) hiện chạy trên mỗi replica; các thao tác cập nhật/xóa đều đã được viết idempotent, tuy nhiên nếu mở rộng quy mô lớn hơn 3–5 replica nên tách `watchdog` thành một worker container đơn lẻ hoặc dùng khóa phân tán Redis.

## Lệnh để người dùng tự kiểm chứng
```powershell
# 1. Chạy toàn bộ 38 bài kiểm thử Backend & Hạ tầng (Postgres 15, Redis 7 SSE 2-instance, Backup/Restore drill):
$env:PYTHONPATH = "$PWD;$PWD\backend"
.\.venv\Scripts\python.exe -m pytest ai/tests backend/tests -v

# 2. Kiểm chứng cấu hình Caddyfile bằng container chính thức:
docker run --rm -e DOMAIN=predrive.example.com -v "${PWD}/infra/caddy/Caddyfile:/etc/caddy/Caddyfile:ro" caddy:2.8-alpine caddy validate --config /etc/caddy/Caddyfile

# 3. Kiểm tra build frontend & Playwright admin-web:
cd frontend; npm run build; cd ../admin-web; npm run typecheck; npm run build; npm test; cd ..
```
