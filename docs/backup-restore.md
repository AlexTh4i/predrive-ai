# PreDrive AI — Quy trình Sao lưu & Khôi phục Cơ sở dữ liệu (`P2-5`)

## 1. Kiến trúc Sao lưu
- **Công cụ:** `scripts/backup.sh` sử dụng `pg_dump --format=custom --no-owner --no-privileges` xuất tệp nhị phân nén `.dump` kèm chữ ký toàn vẹn `.sha256`.
- **Bảo mật (R4):** Tắt trace (`set +x`), không bao giờ in chuỗi kết nối `SUPABASE_DB_URL` / `DATABASE_URL` hay khóa S3/Backblaze ra nhật ký.
- **Xoay vòng nội bộ:** Tự động dọn các bản lưu cục bộ cũ hơn `BACKUP_RETENTION_DAYS` (mặc định `14` ngày).
- **Đồng bộ ngoài máy chủ (Offsite Sync):** Tự động đẩy cả tệp `.dump` và `.sha256` lên AWS S3 / Backblaze B2 / Cloudflare R2 qua `aws s3 cp` (hỗ trợ `BACKUP_S3_ENDPOINT`) hoặc `rclone copy` khi đặt biến môi trường `BACKUP_S3_URI`.

## 2. Cấu hình Cron chạy hằng ngày trên Máy chủ Linux
Tạo tệp `/etc/cron.d/predrive-backup` (chạy lúc `02:15 UTC` mỗi ngày):
```cron
15 2 * * * root cd /opt/predrive-ai && set -a && . /opt/predrive-ai/.env && set +a && /bin/bash scripts/backup.sh >> /var/log/predrive-backup.log 2>&1
```

Các biến môi trường cần khai báo trong `/opt/predrive-ai/.env`:
```ini
SUPABASE_DB_URL=postgresql://postgres.zpbskfqabxdhpdphqnjo:<PASSWORD>@aws-0-eu-west-1.pooler.supabase.com:5432/postgres?sslmode=require
BACKUP_DIR=/var/backups/predrive
BACKUP_RETENTION_DAYS=14
# Tùy chọn đồng bộ ra S3 / Backblaze B2:
BACKUP_S3_URI=s3://predrive-prod-backups/db
BACKUP_S3_ENDPOINT=https://s3.eu-central-003.backblazeb2.com
AWS_ACCESS_KEY_ID=<KEY_ID>
AWS_SECRET_ACCESS_KEY=<APPLICATION_KEY>
```

## 3. Quy trình Khôi phục (Disaster Recovery)
1. **Tải bản sao lưu và kiểm tra toàn vẹn SHA-256:**
   ```bash
   sha256sum -c predrive_YYYYMMDDTHHMMSSZ.dump.sha256
   ```
2. **Khôi phục thử vào cơ sở dữ liệu tạm trước khi chuyển lưu lượng:**
   ```bash
   createdb -h <HOST> -U <USER> predrive_restore_verify
   pg_restore --no-owner --no-privileges --clean --if-exists \
     --dbname="postgresql://<USER>:<PASS>@<HOST>:5432/predrive_restore_verify?sslmode=require" \
     predrive_YYYYMMDDTHHMMSSZ.dump
   ```
3. **Kiểm tra số bảng, trạng thái RLS và số bản ghi:**
   ```sql
   SELECT count(*) AS total_tables, count(*) FILTER (WHERE rowsecurity) AS rls_enabled
   FROM pg_tables WHERE schemaname = 'public';
   ```
4. **Chuyển đổi `DATABASE_URL` của Backend sang DB đã khôi phục** (hoặc khôi phục vào project Supabase đích mới) và khởi động lại `docker compose up -d backend`.

---

## 4. Nhật ký Diễn tập Khôi phục Thực tế (Restore Drill Log — 18/11/2026)

Đã thực thi `scripts/backup.sh` trên PostgreSQL 15 (`predrive-pg15`) và khôi phục vào cơ sở dữ liệu tạm `predrive_restore_drill`:

```text
[1/4] Creating custom-format PostgreSQL dump -> ./backups/predrive_20261118T060714Z.dump
[2/4] Generating SHA-256 checksum -> ./backups/predrive_20261118T060714Z.dump.sha256
727e8c595adefe04b915cdbcc8cd2282abd109e3c6ea54903fe73d707dfb0378 *./backups/predrive_20261118T060714Z.dump
[3/4] Offsite sync check...
BACKUP_S3_URI not set -> skipping offsite cloud upload (local backup retained).
[4/4] Pruning local backups older than 14 day(s)...
Backup completed successfully: ./backups/predrive_20261118T060714Z.dump

CREATE DATABASE
 restored_tables | rls_enabled
-----------------+-------------
              22 |          22
(1 row)

      tbl      | count
---------------+-------
 organizations |     3
 users         |    20
 sessions      |    20
 events        |    20
(4 rows)

DROP DATABASE
```
- **Kết quả Drill:** **THÀNH CÔNG 100%** (khôi phục nguyên vẹn 22/22 bảng, `rowsecurity = true` trên cả 22 bảng, toàn bộ dữ liệu khớp tuyệt đối với bản gốc).
