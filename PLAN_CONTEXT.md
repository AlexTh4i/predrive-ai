# PREDRIVE AI — KẾ HOẠCH TRIỂN KHAI GIAI ĐOẠN 1 → 3 (PLAN CONTEXT)

> **Ngày lập:** 16/11/2026  
> **Phạm vi tài liệu này:** Chỉ bao gồm **Giai đoạn 1 → Giai đoạn 3** (gộp code nhóm, nối thông toàn bộ App Tài xế ↔ Máy chủ ↔ Web Admin, hoàn thiện trải nghiệm & đóng gói `.apk` mới). **Không bao gồm Giai đoạn 4** (nghiên cứu AI nâng cao / thiếu sáng / NTHU-DDD).  
> **Đối tượng sử dụng:** Quản lý dự án (đọc phần tóm tắt dễ hiểu) và các thành viên / AI Coding Assistants (đọc checklist kỹ thuật & điểm lệch cần sửa).

---

## 1. Bức tranh hiện tại (Tính đến 16/11/2026)

### 1.1. Tóm tắt 3 mảnh ghép đã có
1. **App Tài xế (`frontend/` + `PreDrive-debug.apk`):**
   - Đã hoàn thiện AI chạy trực tiếp trên điện thoại (`@mediapipe/tasks-vision`), giao diện tối giản kiểu Grab, linh vật vẹt xanh (`ParrotMascot.tsx`), chuông báo động (`useBellAlarm.ts`) và đã đóng gói được file APK chạy độc lập.
   - **Điểm thiếu:** Chưa kết nối với Máy chủ M3 (chưa đăng nhập tài xế, chưa gửi nhịp tim hay sự kiện buồn ngủ về văn phòng).
2. **Web Admin (`admin-web/` — do Kenneth đẩy lên GitHub):**
   - Đã hoàn thiện 5 màn hình cho **Người trực** và **Quản lý**: Đăng nhập (`/login`), Giám sát trực tiếp (`/`), Lịch sử (`/history`), Danh sách & Hồ sơ tài xế (`/drivers`, `/drivers/:id`), Thống kê (`/stats`), Cài đặt (`/settings`).
   - Đã có nút **Gọi điện (`tel:`)** và **Nhắn Zalo (`https://zalo.me/...`)** miễn phí, kèm nút xác nhận **"Đã liên hệ"**, chuông báo trên tab đang mở, và bộ test Playwright.
   - **Điểm thiếu:** Mặc định đang chạy dữ liệu giả (`mockApi.ts`), chưa chạy ghép với máy chủ thật; chưa có UI gọi 2 API tạo tài xế & tạo mã ghép xe.
3. **Máy chủ & Kho dữ liệu (`backend/` — do Gia Huy đẩy lên GitHub):**
   - Đã hoàn thiện DB SQLite WAL / PostgreSQL (`alembic`), JWT Auth, SSE (`/api/v1/live/stream`), watchdog tự phát hiện mất kết nối (`DISCONNECTED`), dữ liệu mẫu 30 ngày (`seed.py`), script giả lập tài xế (`scripts/simulate_driver.py`), và 6 test tích hợp (`backend/tests/test_m3_backend.py`).
   - Có sẵn tài liệu hợp đồng `docs/api-contract.md` (v0.3) và `docs/openapi.json`.

### 1.2. Trạng thái Git hiện tại
- Nhánh local `main` và `origin/main` đang ở commit `0de723b` (bản M1 + M2 + M2.5 cũ).
- Nhánh `origin/feature/kenneth-admin-web` (`6b9d56b`) chứa phần `admin-web/` + `docs/research-web.md`.
- Nhánh `origin/backend` (`efd27be`) chứa phần `backend/` M3 + `scripts/` **và đã merge sẵn `feature/kenneth-admin-web` vào cùng**.

### 1.3. Mô hình 3 vai trò chuẩn của hệ thống
Giống cách tổ chức của các hệ thống lớn (như Samsara), hệ thống tách rõ 3 vai trò trong từng nhà xe (`organizationId`):
- **Tài xế (`driver`):** Chỉ dùng App điện thoại con vẹt khi lái xe, không vào Web Admin.
- **Người trực / Trực ban (`dispatcher`):** Nhân viên trực ca ngồi theo dõi màn hình Web Admin, thấy báo động đỏ thì bấm **Gọi / Nhắn Zalo** cho tài xế rồi xác nhận **"Đã liên hệ"**. Không thấy và không sửa được mục *Cài đặt hệ thống*.
- **Quản lý (`manager`):** Quản lý đội xe của nhà xe (khách hàng dùng phần mềm), có toàn quyền như Người trực + chỉnh *Cài đặt hệ thống* (ngưỡng lái liên tục, thời gian nghỉ, chia sẻ vị trí) + tạo tài xế & mã ghép xe.

---

## 2. Quyết định sản phẩm đã thống nhất

1. **Giữ cơ chế Gọi & Nhắn Zalo của Kenneth:**
   - Khi trực ban thấy cảnh báo trên Web Admin, bấm nút **Gọi (`tel:+84...`)** hoặc **Nhắn Zalo (`https://zalo.me/84...`)** để mở app Zalo cá nhân nhắn/gọi trực tiếp cho tài xế. Cơ chế này **miễn phí 100%** và sát thực tế tại Việt Nam.
   - Không dùng Zalo OA / ZNS tự động vì bắt buộc phải có giấy phép đăng ký kinh doanh và mất phí ~210–400đ/tin nhắn.
2. **Tách rõ 2 chiều liên lạc cho Giai đoạn 3 (chọn 1 trong 2 phương án khi triển khai):**
   - **Phương án A (Gọn nhất — Không cần app chat thứ ba):** Chỉ dùng Web Admin kêu chuông + bật **Thông báo nổi trên trình duyệt (Web Notification)** khi tab đang thu nhỏ + nút Gọi/Zalo của Kenneth.
   - **Phương án B (Thêm báo khẩn tự động khi quản lý rời máy):** Giữ nút Gọi/Zalo trên web để gọi tài xế; riêng phần máy chủ tự động nhắc quản lý khi ca `CRITICAL` quá 1–2 phút chưa ai bấm *"Đã liên hệ"* thì dùng **Email (Gmail SMTP)** hoặc **Telegram Bot** miễn phí.

---

## 3. Kế hoạch chi tiết Giai đoạn 1 → Giai đoạn 3

### Giai đoạn 1: Gộp code nhóm & Chạy thông Web Admin với Máy chủ thật

**Mục tiêu dễ hiểu:** Gom code mới của cả nhóm về bản chính, bật máy chủ thật và cho Web Admin cắm thẳng vào máy chủ đó (tắt dữ liệu giả) để kiểm tra mọi màn hình chạy trơn tru.

#### Danh sách việc kỹ thuật cần làm:
1. **Đồng bộ Git về nhánh chính:**
   - Kiểm tra diff và merge `origin/backend` (`efd27be`) về nhánh `main` (có thể test trên nhánh tạm trước khi merge vào `main`).
2. **Cài đặt môi trường & Kiểm tra thư viện:**
   - Cài các gói mới ở `backend/requirements.txt` (`sqlalchemy`, `alembic`, `PyJWT`, `argon2-cffi`, `sse-starlette`, `tzdata`, v.v.) vào `venv`.
   - Kiểm tra lỗi thiếu dependency `ai/` khi chạy `backend` trên máy mới (`backend/app/main.py` vẫn `import DriverMonitorAI` từ `ai/` — cần bảo đảm cài đủ hoặc tách import an toàn khi chạy chế độ M3-only).
   - Cài gói cho Web Admin: `cd admin-web; npm install`.
3. **Sửa các điểm lệch giữa `admin-web/` và `backend/`:**
   - **CORS trong `backend/app/main.py`:** Bổ sung `http://localhost:5174`, `http://127.0.0.1:5174`, `http://localhost:4174` vào `PREDRIVE_ALLOWED_ORIGINS` mặc định (tránh lỗi CORS khi chạy `preview` hoặc gọi trực tiếp không qua Vite proxy).
   - **Đồng bộ thông tin tài khoản demo:** Tài khoản seed thật trong `backend/app/services/seed.py` dùng `manager / manager123` và `dispatcher / dispatcher123` (trong khi mock ở `admin-web` dùng `predrive123`). Cập nhật hướng dẫn rõ ràng hoặc đồng bộ nút demo nếu cần.
   - **Kiểm tra khớp SSE & Event ack:** Xác nhận luồng `GET /api/v1/live/stream` (events `driver_state`, `alert`, `: keep-alive`) và `POST /api/v1/events/{id}/ack` hoạt động ổn định với `admin-web/src/api/httpApi.ts`.
   - **Kiểm tra script `copy-ai-assets.mjs`:** Thống nhất một đường dẫn duy nhất giữa `scripts/copy-ai-assets.mjs` (đã thêm ở `origin/backend`) và `frontend/scripts/copy-ai-assets.mjs` (của `main`).
4. **Chạy kiểm thử tích hợp Backend ↔ Web Admin:**
   - Chạy toàn bộ test backend: `pytest ai/tests backend/tests -v` (kỳ vọng toàn bộ 18 bài test pass).
   - Tạo `admin-web/.env` với `VITE_USE_MOCK=false`, bật Backend (`:8000`) + Admin Web (`:5174`), đồng thời chạy `scripts/simulate_driver.py`.

#### Tiêu chí hoàn thành Giai đoạn 1:
- [ ] Nhánh `main` có đầy đủ code mới chạy ổn định, `pytest` pass 100%.
- [ ] Đăng nhập được vào Web Admin bằng dữ liệu thật (`manager / manager123` và `dispatcher / dispatcher123`).
- [ ] Thấy dữ liệu lịch sử 30 ngày từ SQLite, phân quyền `dispatcher` bị ẩn trang `/settings`, và thấy tín hiệu giả lập từ `simulate_driver.py` nhảy live qua SSE.

---

### Giai đoạn 2: Nối App Tài xế (`frontend/` & `.apk`) vào Máy chủ M3

**Mục tiêu dễ hiểu:** Giúp điện thoại gắn trên xe gửi được trạng thái và cảnh báo buồn ngủ về Web Admin theo thời gian thực, kể cả khi đi qua chỗ mất sóng 4G thì tự lưu lại rồi gửi bù sau. Sau đó xuất file cài đặt `.apk` mới để test thật.

#### Danh sách việc kỹ thuật cần làm:
1. **Cấu hình kết nối Server từ App Mobile / Capacitor:**
   - Hiện `frontend/src/config/env.ts` dùng `window.location.origin` (trong Android APK với `androidScheme: 'https'`, giá trị này là `https://localhost`, không gọi được ra máy chủ).
   - Thêm cấu hình `VITE_BACKEND_URL` + màn hình/hộp thoại nhập **Địa chỉ Máy chủ** trên App (lưu `localStorage`) để linh hoạt khi demo qua LAN hoặc tunnel HTTPS.
   - Giải quyết vấn đề **Mixed Content** nếu backend chạy `http://` trong LAN (cấu hình `CapacitorHttp` hoặc `androidScheme: 'http'` + `usesCleartextTraffic` khi dev, hoặc chạy backend qua `https://` tunnel), và mở CORS trên `backend/app/main.py` cho origin của App (`https://localhost`, `http://localhost`, `capacitor://localhost`).
2. **Luồng Đăng nhập & Ghép xe trên App (`frontend/`):**
   - Bổ sung màn hình/ngăn kéo thiết lập cho tài xế:
     - Đăng nhập (`POST /api/v1/auth/login`) lưu JWT + thông tin tài xế/xe.
     - Nhập mã ghép xe 6 ký tự (ví dụ `PAIR01`, gọi `POST /api/v1/auth/pair`) kèm thông báo đồng ý giám sát (`consentedAt`).
   - Cho phép chọn giữ nút "Dùng thử không cần mạng" (chế độ chạy offline cục bộ) hoặc "Kết nối về văn phòng" (mặc định khi đã đăng nhập).
3. **Đồng bộ Phiên, Nhịp tim & Sự kiện lên Máy chủ M3:**
   - Khi bấm **Bắt đầu giám sát**: sinh `sessionId` (UUID), gọi `POST /api/v1/sessions` và nhận `settings` (`heartbeatIntervalSec`, ngưỡng lái liên tục...).
   - **Heartbeat định kỳ:** theo `heartbeatIntervalSec` (mặc định `30s`), gọi `POST /api/v1/sessions/{id}/heartbeat` gửi `state`, `imageQuality`, `continuousDrivingSec`, `vehicleMoving`, `capturedAt` (chỉ gửi `location` khi `settings.shareLocation === true` và người dùng cấp quyền).
   - **Ghi nhận & Đẩy sự kiện buồn ngủ/mất tập trung:** khi `useDriverAI` chuyển sang `DROWSINESS_SIGNS`, `DISTRACTED`, hoặc `CRITICAL`, tạo bản ghi sự kiện (`eventId` UUID) và đẩy lên `POST /api/v1/sessions/{id}/events/batch`.
   - **Hàng đợi Offline (Offline Queue):** lưu các sự kiện chưa gửi thành công vào `localStorage` / `IndexedDB`; tự động gửi bù theo batch khi có mạng trở lại (backend sẽ tự gắn `delayed = true` nếu trễ quá 60s).
   - Khi bấm **Dừng giám sát**: gọi `POST /api/v1/sessions/{id}/end` kèm tổng kết (`totalDrivingSec`, `warningCount`, `criticalCount`, `unavailableSec`).
4. **Dọn gọn UI App Tài xế & Đóng gói `.apk` mới:**
   - Gỡ nút "Quản trị" trỏ sang `AdminStub.tsx` cũ trong `frontend/src/features/driver/DriverScreen.tsx` & `App.tsx` (tránh gây nhầm lẫn trên app tài xế).
   - Build lại Android `.apk` bằng lệnh sạch (`.\gradlew.bat clean :app:assembleDebug` để tránh lỗi Gradle cache bản cũ) và xuất ra `D:\CDIO4\PreDrive-debug.apk`.

#### Tiêu chí hoàn thành Giai đoạn 2:
- [ ] Cài `PreDrive-debug.apk` mới lên điện thoại Android, đăng nhập bằng `driver1 / driver123`.
- [ ] Bấm *Bắt đầu giám sát* $\rightarrow$ Web Admin trên máy tính chuyển trạng thái `driver1` sang `NORMAL` (Trực tuyến).
- [ ] Nhắm mắt 2 giây trên điện thoại $\rightarrow$ Con vẹt rung chuông tại xe **đồng thời** Web Admin hiện cảnh báo đỏ `CRITICAL` và phát chuông ngay lập tức.
- [ ] Tắt Wi-Fi/4G trên điện thoại, tạo cảnh báo rồi bật mạng lại $\rightarrow$ sự kiện tự đồng bộ bù vào tab *Lịch sử* trên Web Admin với nhãn gửi muộn.

---

### Giai đoạn 3: Hoàn thiện Web Admin, Báo động ngoài màn hình & Tài liệu

**Mục tiêu dễ hiểu:** Tinh chỉnh những chi tiết giúp trực ban thao tác nhanh hơn khi có sự cố, bổ sung giao diện tạo tài xế cho Quản lý, thêm cảnh báo khi rời mắt khỏi tab web và cập nhật lại tài liệu tổng quan dự án.

#### Danh sách việc kỹ thuật cần làm:
1. **Tiện ích thao tác nhanh trên Web Admin (`admin-web/`):**
   - Thêm nút tắt **Gọi / Nhắn Zalo** ngay trên từng thẻ cảnh báo ở Dashboard (`AlertListItem.tsx`) hoặc thẻ tài xế (trước đó mới có ở trang `DriverDetail.tsx`), giúp trực ban bấm liên hệ ngay không cần chuyển trang.
   - Bổ sung giao diện cho `manager` sử dụng 2 API backend đã làm sẵn: **Tạo tài khoản tài xế** (`POST /api/v1/drivers`) và **Tạo mã ghép xe** (`POST /api/v1/pairing-codes`).
   - (Tùy chọn nhỏ): Phát sự kiện SSE cập nhật khi có người bấm `POST /events/{id}/ack` để nhiều tab trực ban mở cùng lúc thấy trạng thái *"Đã liên hệ"* đồng bộ ngay.
2. **Nâng cấp báo động ngoài tab trình duyệt:**
   - Thêm **Browser Web Notification API** trên `admin-web/` (xin quyền thông báo khi người trực bật công tắc âm báo): khi có cảnh báo `CRITICAL` mới lúc tab đang ẩn/thu nhỏ, hệ thống bật thông báo nổi kèm âm thanh.
   - *(Theo lựa chọn Phương án A hoặc B ở Mục 2)*: Nếu chọn Phương án B, bổ sung tác vụ leo thang cảnh báo ở `backend/` — sau `N` phút có sự kiện `CRITICAL` chưa `ack`, tự động gửi **Email** hoặc **Telegram Bot** cho quản lý (có chống gửi trùng theo `eventId`).
3. **Kiểm tra thực tế liên kết Zalo / Gọi trên thiết bị thật & Cập nhật tài liệu:**
   - Bấm test thử nút `tel:` và `https://zalo.me/...` từ trình duyệt điện thoại và máy tính thật.
   - Cập nhật [PROJECT_CONTEXT.md](file:///d:/CDIO4/PROJECT_CONTEXT.md) phản ánh đúng kiến trúc mới (`admin-web/`, `backend/` M3, App Mobile M3, và sửa hướng dẫn build APK dùng `clean :app:assembleDebug`).

#### Tiêu chí hoàn thành Giai đoạn 3:
- [ ] Quản lý tạo được tài xế mới + mã ghép đôi ngay trên Web Admin, tài xế nhập mã đó trên App điện thoại là chạy được.
- [ ] Trực ban thu nhỏ cửa sổ trình duyệt vẫn nhận được thông báo nổi khi có `CRITICAL`, bấm 1 chạm mở Zalo/Gọi cho tài xế ngay tại Dashboard.
- [ ] Tài liệu `PROJECT_CONTEXT.md` khớp 100% với mã nguồn thực tế (sẵn sàng để demo và báo cáo).

---

## 4. Thông tin tham chiếu nhanh (Kiểm chứng từ code hiện có)

### Cổng dịch vụ khi chạy local
| Thành phần | Thư mục | Cổng | Ghi chú |
|---|---|---|---|
| **Backend FastAPI (M3 + Legacy WS)** | `backend/` | `http://127.0.0.1:8000` | Swagger tại `/docs`, DB mặc định SQLite `backend/predrive.db` |
| **Web Admin (Quản lý & Trực ban)** | `admin-web/` | `http://localhost:5174` | Proxy `/api/v1` $\rightarrow$ `:8000`; đặt `VITE_USE_MOCK=false` trong `.env` để chạy thật |
| **Driver PWA (Dev Web)** | `frontend/` | `https://localhost:5173` | Dùng `@vitejs/plugin-basic-ssl`, proxy `/api`, `/ws`, `/health` $\rightarrow$ `:8000` |

### Tài khoản mẫu khi nối Máy chủ thật (`backend/app/services/seed.py`)
| Vai trò | Tên đăng nhập | Mật khẩu | Ghi chú |
|---|---|---|---|
| **Quản lý (`manager`)** | `manager` | `manager123` | Quyền cao nhất trong tổ chức |
| **Người trực (`dispatcher`)** | `dispatcher` | `dispatcher123` | Giám sát & xác nhận liên hệ, không sửa Settings |
| **Tài xế (`driver`)** | `driver1` .. `driver5` | `driver123` | Đã gán sẵn 5 xe và mã ghép `PAIR01` .. `PAIR05` |

*(Lưu ý: Trên `admin-web` ở chế độ giả lập mock, mật khẩu demo hiện là `predrive123` — sẽ cần đồng bộ hoặc tắt mock ở Giai đoạn 1).*

### Lưu ý build lại Android APK (Mục 9.4)
Luôn dùng `clean` trước `assembleDebug` để Gradle không đóng gói lại bundle cũ:
```powershell
cd D:\CDIO4\frontend
npm run build
npx cap sync android
cd D:\CDIO4\frontend\android
.\gradlew.bat clean :app:assembleDebug --no-daemon
Copy-Item "D:\CDIO4\frontend\android\app\build\outputs\apk\debug\app-debug.apk" "D:\CDIO4\PreDrive-debug.apk" -Force
```

