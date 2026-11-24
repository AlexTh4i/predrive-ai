# Báo cáo Phase 0 — Cơ sở dữ liệu PostgreSQL + Supabase

## Phase / ID đã xong
- `P0-1`: Kiểm chứng `supabase/schema.sql` (22 bảng, 5 kiểu Enum, RLS `rowsecurity=true`, 2 Views `v_events_pending_escalation` & `v_driver_usage_7d`, 3 hàm `current_org_id()`, `nearest_rest_stops()`, `purge_old_data()`) và `supabase/seed.sql` trên container PostgreSQL 15 sạch (`postgres:15-alpine`); bổ sung `scripts/hash_seed_passwords.py`.
- `P0-2`: Đồng bộ 100% `backend/app/models/models.py` (22 ORM models dùng kiểu portable `UUIDStr`, `JSONBType`, `INETType`, `StringArrayType`, PostgreSQL Enums) và tạo Alembic migration `backend/migrations/versions/0002_production_schema_v1.py` khớp tuyệt đối với `supabase/schema.sql` (đối chiếu tự động qua `information_schema.columns`).
- `P0-3`: Cấu hình `DATABASE_URL` hỗ trợ song song SQLite WAL (dev) và PostgreSQL/Supabase (prod), tự gắn `sslmode=require` cho host Supabase và tắt `prepare_threshold` / dùng `NullPool` khi chạy qua Transaction/Session Pooler; chạy toàn bộ bộ kiểm thử M3 trên cả hai hệ quản trị CSDL.
- `P0-4`: Viết lại `backend/app/services/seed.py` tạo dữ liệu đa công ty (3 tổ chức, 20 người dùng, xe, trạm dừng nghỉ QL1A, chính sách leo thang, consents, điểm rủi ro, nhật ký) và chặn tuyệt đối việc tạo tài khoản mẫu khi `ENV=production`.
- `P0-5`: Hoàn thiện `scripts/push_to_supabase.sh` (tắt trace `set +x` chống lộ chuỗi kết nối, tự chuyển sang Session Pooler `aws-0-eu-west-1.pooler.supabase.com:5432` nếu host trực tiếp lỗi IPv6, chặn ghi đè DB không rỗng, bỏ qua `seed.sql` khi `ENV=production`, kiểm tra `pg_tables.rowsecurity` trên cả 22 bảng và in `count(*)`).

## File đã tạo/sửa
- Tạo mới:
  - `ANTIGRAVITY_BRIEF.md`
  - `supabase/schema.sql`
  - `supabase/seed.sql`
  - `scripts/hash_seed_passwords.py`
  - `scripts/push_to_supabase.sh`
  - `backend/migrations/versions/0002_production_schema_v1.py`
  - `backend/tests/test_p0_sql.py`
  - `docs/reports/phase-0.md`
- Đã sửa:
  - `backend/requirements.txt` (thêm `psycopg[binary]>=3.2,<4.0`)
  - `backend/.env.example`
  - `backend/alembic.ini`
  - `backend/app/core/config.py`
  - `backend/app/core/database.py`
  - `backend/app/models/models.py` & `backend/app/models/__init__.py`
  - `backend/app/schemas/m3.py`
  - `backend/app/services/events_service.py`
  - `backend/app/services/mappers.py`
  - `backend/app/services/watchdog.py`
  - `backend/app/services/seed.py`
  - `backend/app/routers/auth.py`
  - `backend/app/routers/driver_app.py`
  - `backend/app/routers/web_admin.py`
  - `backend/app/main.py`
  - `backend/scripts/seed.py`
  - `PROJECT_CONTEXT.md`

## Kết quả test (pytest, Playwright, build)
- **Pytest (`ai/tests` + `backend/tests` trên SQLite & PostgreSQL 15):** `23/23 xanh` (`13.08s`)
- **Playwright (`admin-web`):** `6/6 xanh` (`32.6s`) + `npm run build` xanh
- **Frontend Driver App (`frontend`):** `npm run build` xanh (`4.11s`)

## DoD đạt / chưa đạt (từng ID)
- `P0-1`: **ĐẠT** — `schema.sql` & `seed.sql` chạy sạch trên Postgres 15, trả đúng số dòng của cả 22 bảng, `rowsecurity = true` trên 22/22 bảng.
- `P0-2`: **ĐẠT** — `alembic upgrade head` tạo đủ 22 bảng khớp `information_schema.columns` với `schema.sql` và `models.py`, không lệch cột hay kiểu dữ liệu.
- `P0-3`: **ĐẠT** — Pytest chạy xanh 100% trên cả SQLite và PostgreSQL 15, hỗ trợ Supabase Session/Transaction Pooler + `sslmode=require`.
- `P0-4`: **ĐẠT** — Khi `ENV=production`, khởi động ứng dụng không tạo bất kỳ user/organization nào (`users = 0`), gọi `seed_database` bị chặn bằng `RuntimeError`.
- `P0-5`: **ĐẠT phần mã nguồn & kiểm thử local trên Postgres 15** (`test_p0_5_push_to_supabase_script_dev_and_prod` xanh cho cả `ENV=development` và `ENV=production`); **BLOCKED bước chạy lên cloud Supabase thật** do biến môi trường `SUPABASE_DB_URL` chưa được cung cấp.

## Mục BLOCKED (cần gì từ người dùng)
- `BLOCKED: cần SUPABASE_DB_URL` để chạy `scripts/push_to_supabase.sh` đẩy schema thực tế lên Supabase project `zpbskfqabxdhpdphqnjo` (`eu-west-1`).

## Rủi ro còn lại / việc tồn đọng
- Tiện ích `pg_cron` trên Supabase cần bật một lần trong mục *Database → Extensions* trên Supabase Dashboard để lịch `0 3 * * *` tự động gọi `purge_old_data()` phía DB (ngoài ra ở Phase 2 `P2-6` backend cũng sẽ có job nền gọi retention hằng ngày để đảm bảo dự phòng kép).

## Lệnh để người dùng tự kiểm chứng
```powershell
# 1. Chạy toàn bộ kiểm thử Backend + Postgres 15 Docker:
$env:PYTHONPATH = "$PWD;$PWD\backend"
.\.venv\Scripts\python.exe -m pytest ai/tests backend/tests -v

# 2. Chạy kiểm thử E2E Playwright cho admin-web:
cd admin-web; npm run build; npm test; cd ..

# 3. Kiểm tra build frontend:
cd frontend; npm run build; cd ..

# 4. Đẩy lên Supabase thật (trong Git Bash, thay mật khẩu DB của project zpbskfqabxdhpdphqnjo):
# export ENV=production
# export SUPABASE_DB_URL='postgresql://postgres.zpbskfqabxdhpdphqnjo:<PASSWORD>@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require'
# bash scripts/push_to_supabase.sh
```
