# PREDRIVE AI — Backend M3 (Fleet Management, Telemetry & Realtime SSE)

Phân hệ Backend của **PreDrive AI** (Milestone 3) phục vụ nhà xe / đội xe đường dài có người trực (`dispatcher`) và quản lý (`manager`), nhận siêu dữ liệu sự kiện & nhịp tim từ ứng dụng tài xế Android (`driver` — AI chạy trực tiếp trên thiết bị, **không truyền và không lưu ảnh/video khuôn mặt**), đồng thời giữ nguyên tương thích ngược với WebSocket Gateway của M1/M2.

---

## 1. Cấu trúc Thư mục

```text
backend/
├── alembic.ini                     # Cấu hình Alembic migration
├── migrations/                     # Lịch sử schema migration (0001_initial_m3_schema.py)
├── scripts/
│   ├── seed.py                     # Script tạo dữ liệu mẫu 30 ngày (Idempotent)
│   └── simulate_driver.py          # Wrapper chạy kịch bản giả lập tài xế
├── app/
│   ├── main.py                     # Khởi tạo FastAPI, lifespan, watchdog, routers & legacy WS
│   ├── core/
│   │   ├── config.py               # Cấu hình biến môi trường (DATABASE_URL, JWT, Retention)
│   │   ├── database.py             # SQLAlchemy 2.x Engine, SessionLocal, SQLite WAL PRAGMA
│   │   ├── errors.py               # Chuẩn hóa lỗi {"error": {"code": "...", "message": "..."}}
│   │   └── security.py             # Argon2id password hashing, JWT Bearer & RBAC
│   ├── models/
│   │   └── models.py               # 9 bảng: organizations, users, vehicles, pairings, sessions, events, heartbeats, settings, locations
│   ├── schemas/
│   │   ├── legacy.py               # Schema WebSocket M1/M2
│   │   └── m3.py                   # Toàn bộ Pydantic v2 camelCase schemas theo Hợp đồng API chung
│   ├── services/
│   │   ├── events_service.py       # Upsert sự kiện idempotent đơn điệu (OPEN -> ESCALATED -> CLOSED)
│   │   ├── mappers.py              # Quy đổi ORM -> DTO & múi giờ Asia/Ho_Chi_Minh (UTC+7)
│   │   ├── seed.py                 # Logic seed 1 tổ chức, 7 tài khoản, 5 xe, 30 ngày dữ liệu
│   │   ├── sse.py                  # Pub/Sub Broker đa kết nối cho luồng SSE /api/v1/live/stream
│   │   └── watchdog.py             # Tác vụ nền phát hiện mất heartbeat -> DISCONNECTED & dọn dữ liệu cũ
│   └── routers/
│       ├── auth.py                 # /api/v1/auth/{login,me,pair}
│       ├── driver_app.py           # /api/v1/sessions, /{id}/{events,events/batch,heartbeat,end}
│       └── web_admin.py            # /api/v1/live, /live/stream, /events, /drivers, /stats/*, /settings, /pairing-codes
└── tests/
    ├── test_gateway.py             # 8/8 bài kiểm thử M1/M2 WebSocket Gateway
    └── test_m3_backend.py          # Bộ kiểm thử M3: RBAC, Multi-org, Idempotency, Delayed, Watchdog, SSE, Simulator
```

---

## 2. Hướng dẫn Cài đặt & Chạy Local

### 2.1. Khởi tạo môi trường ảo & cài đặt thư viện
Từ thư mục gốc của repo (`predrive-ai/`):
```powershell
python -m venv --system-site-packages .venv
.\.venv\Scripts\pip install -r backend/requirements.txt
```

### 2.2. Chạy Migration (Alembic) & Seed dữ liệu mẫu (Idempotent)
```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
cd ..
.\.venv\Scripts\python.exe scripts/seed.py
```
> **Lưu ý:** Khi khởi động FastAPI lần đầu trên DB trống, hệ thống cũng tự động tạo bảng và seed dữ liệu nếu `PREDRIVE_AUTO_SEED=1` (mặc định). Bạn có thể chạy `scripts/seed.py` nhiều lần mà không sợ trùng dữ liệu.

### 2.3. Tài khoản mặc định sau khi Seed
| Vai trò (`role`) | `username` | `password` | Họ tên | Ghi chú |
|---|---|---|---|---|
| **Quản lý (`manager`)** | `manager` | `manager123` | Nguyễn Quốc Quản Lý | Toàn quyền xem + sửa `Settings`, tạo tài xế & mã ghép xe |
| **Người trực (`dispatcher`)** | `dispatcher` | `dispatcher123` | Trần Thị Trực Ban | Xem `/live`, `/events`, `/stats`, ghi nhận `ack` ("Đã liên hệ") |
| **Tài xế 1 (`driver`)** | `driver1` | `driver123` | Nguyễn Văn An | Xe `51B-123.45 - Giường nằm 40 chỗ` |
| **Tài xế 2 (`driver`)** | `driver2` | `driver123` | Trần Minh Bình | Xe `51B-234.56 - Limousine 34 phòng` |
| **Tài xế 3 (`driver`)** | `driver3` | `driver123` | Lê Hoàng Cường | Xe `51B-345.67 - Giường nằm 40 chỗ` |
| **Tài xế 4 (`driver`)** | `driver4` | `driver123` | Phạm Quốc Dũng | Xe `51C-456.78 - Xe tải đường dài 15T` |
| **Tài xế 5 (`driver`)** | `driver5` | `driver123` | Võ Thanh Hải | Xe `51C-567.89 - Đầu kéo Container` |

### 2.4. Khởi chạy Server FastAPI
```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000 --reload
```
- **Swagger UI (OpenAPI):** `http://127.0.0.1:8000/docs`
- **OpenAPI JSON:** `http://127.0.0.1:8000/openapi.json` (bản xuất tĩnh tại `docs/openapi.json`)

---

## 3. Chạy Script Giả lập Tài xế (`simulate_driver.py`) & Thử Realtime SSE bằng `curl`

### Bước 1: Mở cửa sổ Terminal theo dõi luồng SSE (`/api/v1/live/stream`)
Trong PowerShell:
```powershell
$res = Invoke-RestMethod -Uri "http://127.0.0.1:8000/api/v1/auth/login" -Method Post -ContentType "application/json" -Body '{"username":"dispatcher","password":"dispatcher123"}'
$token = $res.accessToken
curl.exe -N -H "Authorization: Bearer $token" "http://127.0.0.1:8000/api/v1/live/stream"
```

### Bước 2: Mở cửa sổ Terminal thứ hai chạy `scripts/simulate_driver.py`
```powershell
.\.venv\Scripts\python.exe scripts/simulate_driver.py
```
Bạn sẽ thấy trên cửa sổ SSE các sự kiện `event: driver_state` và `event: alert` được đẩy về theo thời gian thực khi tài xế mở phiên, gửi heartbeat, chuyển trạng thái `OPEN -> ESCALATED -> CLOSED`, và **không** phát `alert` đối với sự kiện offline có `delayed = true`.

---

## 4. Chạy Bộ Kiểm thử Tự động (Pytest)

```powershell
$env:PYTHONPATH = "$PWD;$PWD\backend"
.\.venv\Scripts\python.exe -m pytest ai/tests backend/tests -v
```
Toàn bộ 18 bài kiểm thử (4 bài AI + 8 bài WebSocket Gateway M1/M2 + 6 bài tích hợp lớn của M3) đều chạy độc lập và tự động.

---

## 5. Chuyển đổi sang PostgreSQL
Mặc định môi trường dev dùng SQLite ở chế độ `WAL` (`backend/predrive.db`). Khi triển khai lên môi trường staging/production với PostgreSQL, chỉ cần đặt biến môi trường:
```powershell
$env:DATABASE_URL = "postgresql+psycopg://user:password@host:5432/predrive"
```
rồi chạy `alembic upgrade head`.
