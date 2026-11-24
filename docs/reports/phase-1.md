# Báo cáo Phase 1 — Bảo mật và Multi-tenant

## Phase / ID đã xong
- `P1-1`: Xóa hoàn toàn mật khẩu mặc định ở production (`ENV=production` → 0 user sau khởi động); sinh mật khẩu tạm ngẫu nhiên khi `manager` tạo tài xế mới và đặt `must_change_password = true`, chặn mọi API nghiệp vụ (`403 PASSWORD_CHANGE_REQUIRED`) cho đến khi đổi mật khẩu qua `POST /api/v1/auth/change-password`.
- `P1-2`: Rút ngắn Access Token xuống **15 phút** (`900s`) kèm **Refresh Token xoay vòng** (chỉ lưu SHA-256 `token_hash` vào bảng `refresh_tokens` theo chuỗi `family_id`); thu hồi khi đăng xuất (`/auth/logout`) hoặc đổi mật khẩu; **phát hiện tái sử dụng token cũ** (`REFRESH_TOKEN_REUSED` → thu hồi toàn bộ `family_id`); tích hợp tự động refresh ngầm trên cả `admin-web/` và `frontend/`.
- `P1-3`: Triển khai `SlidingWindowRateLimiter` tự động dùng **Redis** khi có `REDIS_URL` và tự fallback sang **in-memory** khi không có Redis; bảo vệ `/auth/login` (theo `IP + username` & `IP`), `/auth/pair`, `/sessions/{id}/events*`, `/sessions/{id}/heartbeat` trả **HTTP `429`** kèm header `Retry-After`.
- `P1-4`: Ghi nhận `audit_logs` chính xác 1 dòng cho từng hành động (`login_success`, `login_failed`, `ack_event`, `update_settings`, `create_driver`, `create_pairing`, `create_api_key`, `revoke_api_key`, `export_report`, `change_password`, `accept_consent`); cung cấp API phân trang `GET /api/v1/audit-logs` dành riêng cho `manager`.
- `P1-5`: **Cách ly Multi-tenant tuyệt đối**: rút `organization_id` trực tiếp từ JWT claim đã xác thực (`get_jwt_org_id`), từ chối JWT lệch tổ chức (`401 ORG_MISMATCH`), không nhận `organization_id` từ client, cô lập hoàn toàn dữ liệu REST, đoán UUID, mã ghép xe, báo cáo, API keys và kênh SSE `/api/v1/live/stream` giữa các công ty.
- `P1-6`: Siết cấu hình production: tắt `/docs`, `/redoc`, `/openapi.json` khi `ENV=production`, kiểm soát CORS động theo `CORS_ORIGINS`, gắn đầy đủ Security Headers (`X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Strict-Transport-Security`, `Content-Security-Policy`) và giới hạn kích thước request body trả `413 PAYLOAD_TOO_LARGE`.
- `P1-7`: Quản lý `consents` theo **Nghị định 13/2023/NĐ-CP** (`GET/POST /api/v1/auth/consent`, khóa cứng `clip_storage_consent = false` theo R1); chặn nhận heartbeat/event trên cả phía App Tài xế (`useDriverSync.ts`, `DriverConnectSheet.tsx`) lẫn phía Server (`403 CONSENT_REQUIRED`) khi tài xế chưa đồng ý.

## File đã tạo/sửa
- Tạo mới:
  - `backend/app/services/rate_limiter.py`
  - `backend/app/services/audit.py`
  - `backend/tests/test_p1_security.py`
  - `docs/reports/phase-1.md`
- Đã sửa:
  - `backend/requirements.txt` (thêm `redis>=5.0,<6.0`)
  - `backend/app/core/errors.py`
  - `backend/app/core/security.py`
  - `backend/app/schemas/m3.py`
  - `backend/app/routers/auth.py`
  - `backend/app/routers/driver_app.py`
  - `backend/app/routers/web_admin.py`
  - `backend/app/main.py`
  - `admin-web/src/types.ts`, `admin-web/src/api/contract.ts`, `admin-web/src/api/httpApi.ts`, `admin-web/src/hooks/useAuth.tsx`, `admin-web/src/pages/Drivers.tsx`
  - `frontend/src/types/m3.ts`, `frontend/src/services/m3Api.ts`, `frontend/src/hooks/useDriverSync.ts`, `frontend/src/components/DriverConnectSheet.tsx`, `frontend/src/features/driver/DriverScreen.tsx`
  - `PROJECT_CONTEXT.md`

## Kết quả test (pytest, Playwright, build)
- **Pytest (`ai/tests` + `backend/tests`, gồm cả Redis & Postgres 15):** `31/31 xanh` (`22.36s`)
- **Playwright (`admin-web`):** `6/6 xanh` + `npm run build` xanh
- **Frontend Driver App (`frontend`):** `npm run build` xanh

## DoD đạt / chưa đạt (từng ID)
- `P1-1`: **ĐẠT** — `ENV=production` không có tài khoản mẫu; user do manager tạo bắt buộc đổi mật khẩu lần đầu trước khi mở phiên lái.
- `P1-2`: **ĐẠT** — Access token 15m + refresh token lưu hash, thu hồi khi logout/đổi mật khẩu, phát hiện replay thu hồi toàn chuỗi `family_id`, client tự refresh.
- `P1-3`: **ĐẠT** — Test xanh trên cả `in_memory` và `redis`, trả đúng HTTP 429 kèm `Retry-After`.
- `P1-4`: **ĐẠT** — Đúng 1 dòng `audit_logs` cho mỗi hành động; `manager` phân trang được qua `/api/v1/audit-logs`, `dispatcher` bị chặn 403.
- `P1-5`: **ĐẠT** — Mọi endpoint, đoán UUID, mã ghép xe, SSE, báo cáo đều cách ly hoàn toàn giữa Công ty A và Công ty B (mở khóa điều kiện sang Phase 3).
- `P1-6`: **ĐẠT** — Production tắt `/docs`, siết CORS theo `CORS_ORIGINS`, trả đủ security headers và trả 413 khi quá dung lượng body.
- `P1-7`: **ĐẠT** — Chưa có consent → App không gửi dữ liệu và Server từ chối heartbeat/event bằng `403 CONSENT_REQUIRED`.

## Mục BLOCKED (cần gì từ người dùng)
- Không có mục BLOCKED trong Phase 1 (toàn bộ chức năng bảo mật & multi-tenant đã hoàn thiện và kiểm thử đầy đủ trên SQLite, Postgres 15 và Redis 7).

## Rủi ro còn lại / việc tồn đọng
- Khi triển khai lên môi trường production thật, người dùng cần đặt `PREDRIVE_JWT_SECRET` ngẫu nhiên tối thiểu 32 ký tự và tạo tài khoản quản lý đầu tiên qua script quản trị nội bộ (do auto-seed đã bị khóa hoàn toàn ở `ENV=production`).

## Lệnh để người dùng tự kiểm chứng
```powershell
# 1. Chạy toàn bộ 31 bài kiểm thử Backend (gồm P1-1 -> P1-7 trên SQLite, Postgres 15 & Redis 7):
$env:PYTHONPATH = "$PWD;$PWD\backend"
.\.venv\Scripts\python.exe -m pytest ai/tests backend/tests -v

# 2. Kiểm tra build frontend & Playwright admin-web:
cd frontend; npm run build; cd ../admin-web; npm run build; npm test; cd ..
```
