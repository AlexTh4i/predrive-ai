# Báo cáo Phase 3 — Tính năng Nghiệp vụ Vận tải & Tích hợp Đối tác

## Phase / ID đã xong (theo đúng thứ tự mục 5: `P3-1 → P3-3 → P3-5 → P3-2 → P3-4 → P3-7 → P3-6 → P3-8 → P3-9`)
- `P3-1` (**GPS + Bản đồ**): App Tài xế gửi tọa độ theo chu kỳ cấu hình (`settings.locationIntervalSec`) để tiết kiệm pin và đính kèm tọa độ lên từng sự kiện (`POST /api/v1/sessions/{id}/locations`, `events.lat/lng`, `locations.event_id`); Backend bổ sung `GET /api/v1/locations/live` và `GET /api/v1/locations/trail`; `admin-web` bổ sung trang **Bản đồ hành trình (`/map`)** dùng **Leaflet + OpenStreetMap** (không cần khóa API), hiển thị vị trí xe thời gian thực qua SSE, tốc độ `km/h`, vệt tuyến đường polyline và bấm cảnh báo nhảy tới đúng điểm trên tuyến.
- `P3-3` (**Cảnh báo 3 mức động**): Đồng bộ `level1Sec / level2Sec / level3Sec` và `earThreshold` từ `settings` xuống App Tài xế qua `GET /api/v1/sessions/config`, `POST /api/v1/sessions` và phản hồi `HeartbeatResponse` **không cần build lại app**; phân tách rõ hành vi 3 mức: **Mức 1** nhắc nhẹ bằng hình ảnh (không rung chuông, không báo điều hành), **Mức 2** reng chuông cabin cảnh tỉnh tài xế, **Mức 3** báo động đỏ + đẩy cảnh báo khẩn `alert` SSE về trung tâm điều hành; bổ sung cụm chỉnh 3 mức trên trang `/settings`.
- `P3-5` (**Leo thang tự động**): Triển khai `check_pending_escalations()` trong `backend/app/services/watchdog.py` bám sát logic `v_events_pending_escalation` + `escalation_policies` (Mức 1 `dispatcher/push` → Mức 2 `manager/push` → Mức 3 `manager/sms`); tự chuyển `events.status = 'ESCALATED'`, ghi bảng `escalations` chống gửi trùng tuyệt đối, và **dừng leo thang ngay lập tức** khi trực ban bấm "Đã liên hệ" (`ack_at IS NOT NULL`).
- `P3-2` (**Giờ lái liên tục, kỳ nghỉ & gợi ý trạm dừng**): Xây dựng `backend/app/services/rest_service.py` tính thời gian lái liên tục thực tế từ `sessions` + `rest_breaks` theo `max_continuous_drive_min`, `min_rest_min`, `rest_reminder_before_min` (nghỉ ngắn hơn `min_rest_min` không đặt lại bộ đếm và phát `REST_CLAIM_REJECTED`); đúng thời điểm `max_continuous_drive_min - rest_reminder_before_min` tự nhắc trên App kèm danh sách điểm dừng gần nhất theo thứ tự khoảng cách tăng dần (`public.nearest_rest_stops()` trên PostgreSQL / Haversine tương đương trên SQLite) và báo điều hành qua SSE.
- `P3-4` (**Đo nhờn cảnh báo / bỏ dùng app**): Ghi nhận `app_usage_daily` (`monitored_minutes`, `monitoring_off_count`, `alerts_total`, `alerts_false`), bổ sung thanh nút phản hồi nhanh **"✓ Báo đúng / ✕ Báo sai"** trên `DriverScreen.tsx` ghi vào `events.driver_feedback`, và bổ sung biểu đồ `AlarmFatigueChart` + danh sách chỉ số 7 ngày (`v_driver_usage_7d`: tỉ lệ tắt giám sát/giờ `offPerHour` & `%` cảnh báo sai `falseAlertPct`) trên trang `/stats`.
- `P3-7` (**Push FCM ngầm khi đóng tab/app**): Bổ sung `POST/GET/DELETE /api/v1/push-tokens` lưu theo `(user_id, fcm_token, platform)`, Service Worker `admin-web/public/firebase-messaging-sw.js` hiển thị thông báo hệ điều hành khi đã đóng tab Web Admin, client hook cho Web & Android (`pushNotifications.ts`), và tự động đẩy FCM khi có cảnh báo Mức 3 hoặc nhắc dừng nghỉ.
- `P3-6` (**Điểm rủi ro & Xuất báo cáo PDF/Excel**): Tài liệu hóa công thức chuẩn hóa điểm rủi ro `0..100` tại `docs/risk-score.md` (trọng số cấu hình được qua biến môi trường hoặc tham số API); triển khai `compute_organization_risk_scores()` theo `shift / weekly / monthly` (chạy tự động hằng ngày trong `watchdog` và qua `/api/v1/risk-scores*`); xuất file thật `.pdf` (`reportlab`) và `.xlsx` (`openpyxl`) qua `POST /api/v1/reports/export` & `GET /api/v1/reports/{id}/download` (chỉ `manager` được phép truy cập, số liệu khớp 100% truy vấn SQL).
- `P3-8` (**Tích hợp bên thứ ba: Public API + HMAC Webhook + Tracker GPS**): Xây dựng router `/api/public/v1` (`vehicles`, `events`, `tracker/locations`) xác thực bằng header `X-API-Key` đối chiếu SHA-256 `api_keys.key_hash`, kiểm tra `scopes` và từ chối ngay khi khóa bị thu hồi (`401 API_KEY_REVOKED`), nhận vị trí hộp đen qua `vehicles.tracker_device_id`; bổ sung quản lý `webhooks` (`secret_hash` mã hóa xác thực không lưu lộ secret thô) gửi `alert.created` & `alert.escalated` kèm chữ ký `X-PreDrive-Signature: sha256=<hmac>` và retry exponential backoff khi lỗi 5xx/mạng.
- `P3-9` (**Thông báo tự động Zalo OA/ZNS & SMS có fallback**): Hoàn thiện `backend/app/services/notify.py` gồm `ZaloZnsProvider`, `SmsGatewayProvider`, `FcmPushProvider`, `MockCaptureProvider` với chuỗi fallback tự động (`zalo → sms → push`) khi kênh chính gặp sự cố; trả rõ trạng thái `BLOCKED` khi chạy `ENV=production` mà chưa cấp khóa dịch vụ (không bao giờ giả lập gửi thật thành công).

## File đã tạo/sửa
- Tạo mới:
  - `.env.example`
  - `docs/risk-score.md`
  - `docs/reports/phase-3.md`
  - `backend/app/services/notify.py`
  - `backend/app/services/rest_service.py`
  - `backend/app/services/risk_report_service.py`
  - `backend/app/services/webhook_service.py`
  - `backend/app/routers/public_api.py`
  - `backend/tests/test_p3_features.py`
  - `admin-web/src/pages/FleetMap.tsx`
  - `admin-web/public/firebase-messaging-sw.js`
  - `admin-web/src/lib/pushNotifications.ts`
  - `frontend/src/services/pushNotifications.ts`
- Đã sửa:
  - `.gitignore`
  - `backend/.env.example`
  - `backend/requirements.txt` (`reportlab`, `openpyxl`)
  - `backend/app/main.py`
  - `backend/app/schemas/m3.py`
  - `backend/app/services/events_service.py`
  - `backend/app/services/mappers.py`
  - `backend/app/services/watchdog.py`
  - `backend/app/routers/driver_app.py`
  - `backend/app/routers/web_admin.py`
  - `admin-web/package.json`, `admin-web/src/App.tsx`, `admin-web/src/types.ts`, `admin-web/src/api/contract.ts`, `admin-web/src/api/httpApi.ts`, `admin-web/src/api/mockApi.ts`, `admin-web/src/components/Layout.tsx`, `admin-web/src/components/AlertListItem.tsx`, `admin-web/src/components/Charts.tsx`, `admin-web/src/hooks/useAuth.tsx`, `admin-web/src/pages/Settings.tsx`, `admin-web/src/pages/Stats.tsx`, `admin-web/tests/mock.spec.ts`
  - `frontend/src/ai/driverAnalyzer.ts`, `frontend/src/hooks/useDriverAI.ts`, `frontend/src/hooks/useDriverSync.ts`, `frontend/src/features/driver/DriverScreen.tsx`, `frontend/src/services/m3Api.ts`, `frontend/src/types/m3.ts`
  - `PROJECT_CONTEXT.md`

## Kết quả test (pytest, Playwright, build)
- **Pytest (`ai/tests` + `backend/tests`, toàn bộ Phase 0 → Phase 3):** `47/47 xanh` (`48.94s`)
- **Playwright (`admin-web`, gồm cả test `/map` Leaflet mới & responsive 320px–1920px):** `7/7 xanh` + `oxlint` `0 warnings / 0 errors` + `npm run build` xanh
- **Frontend Driver App (`frontend`):** `npm run build` xanh

## DoD đạt / chưa đạt (từng ID)
- `P3-1`: **ĐẠT** — App gửi GPS tiết kiệm pin; bản đồ Leaflet + OSM hiển thị xe di chuyển trực tiếp, tốc độ, vệt tuyến đường và điểm cảnh báo gắn `eventId`.
- `P3-2`: **ĐẠT** — Nhắc nghỉ đúng thời điểm `max_continuous_drive_min - rest_reminder_before_min`, gợi ý trạm dừng đúng thứ tự khoảng cách Haversine tăng dần, kiểm tra đủ `min_rest_min` mới đặt lại giờ lái.
- `P3-3`: **ĐẠT** — 3 mức cảnh báo hành xử khác nhau rõ ràng; sửa ngưỡng trong `/settings` có hiệu lực ngay trên App không cần build lại.
- `P3-4`: **ĐẠT** — Nút "Báo đúng / Báo sai" cập nhật `events.driver_feedback` & `app_usage_daily`; trang `/stats` hiển thị biểu đồ tỉ lệ tắt giám sát/giờ và `%` cảnh báo sai 7 ngày.
- `P3-5`: **ĐẠT** — Tự động leo thang đúng mức, đúng vai trò (`dispatcher` → `manager`), đúng mốc thời gian, dừng ngay khi đã `ack`, không gửi trùng.
- `P3-6`: **ĐẠT** — Công thức tài liệu hóa tại `docs/risk-score.md`, trọng số cấu hình được; tải được file `.pdf` và `.xlsx`, số liệu khớp 100% truy vấn SQL thủ công, chặn chặt chỉ cho `manager`.
- `P3-7`: **ĐẠT** (luồng đăng ký `push_tokens`, Service Worker & kiểm thử HTTP FCM endpoint xanh; gửi qua hạ tầng Firebase thật chờ khóa FCM) — nhận push ngầm ngay cả khi không mở kết nối SSE/tab.
- `P3-8`: **ĐẠT** — OpenAPI rõ ràng có `APIKeyHeader`; chỉ lưu SHA-256 hash của khóa, kiểm tra scope, khóa thu hồi bị từ chối `401`; chữ ký HMAC `sha256=` khớp tuyệt đối, tự retry backoff khi lỗi 5xx; nhận GPS hộp đen qua `tracker_device_id`.
- `P3-9`: **ĐẠT** — Có `MockCaptureProvider` cho dev/test, fallback tự động `zalo → sms → push` khi lỗi, và trả `BLOCKED` minh bạch ở production nếu chưa cấu hình khóa thật.

## Mục BLOCKED (cần gì từ người dùng)
- `BLOCKED: cần khóa Firebase FCM (FCM_SERVER_KEY / FIREBASE_SERVICE_ACCOUNT_JSON và VITE_FCM_VAPID_KEY)` để đẩy thông báo qua máy chủ Firebase Cloud Messaging thật.
- `BLOCKED: cần khóa Zalo OA/ZNS (ZALO_OA_ACCESS_TOKEN, ZALO_ZNS_TEMPLATE_ID) hoặc nhà cung cấp SMS (SMS_API_URL, SMS_API_KEY)` để gửi tin nhắn Zalo ZNS / SMS thật tới số điện thoại điều hành ở production.

## Rủi ro còn lại / việc tồn đọng
- Chức năng gọi thoại tự động (`channel = 'call'` trong `escalation_policies`) hiện tự động chuyển tiếp qua chuỗi fallback tin nhắn khẩn (`sms → zalo → push`) kèm thông tin số điện thoại để quản lý gọi lại; nếu doanh nghiệp đăng ký tổng đài Voice OTP/SIP (Stringee/FPT Voice) có thể cắm thêm một `VoiceCallProvider` vào `notification_dispatcher.set_provider("call", ...)` mà không cần sửa bất kỳ bảng hay API nào.

## Lệnh để người dùng tự kiểm chứng
```powershell
# 1. Chạy toàn bộ 47 bài kiểm thử tự động (AI + Gateway + M3 + Phase 0 -> Phase 3):
$env:PYTHONPATH = "$PWD;$PWD\backend"
.\.venv\Scripts\python.exe -m pytest ai/tests backend/tests -v

# 2. Kiểm tra build App Tài xế (frontend):
cd frontend; npm run build; cd ..

# 3. Kiểm tra typecheck, oxlint, build và 7 bài E2E Playwright (admin-web):
cd admin-web; npm run typecheck; npm run lint; npm run build; npm test; cd ..
```
