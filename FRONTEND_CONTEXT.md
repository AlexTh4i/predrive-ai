# CONTEXT 02 – Frontend / PWA Engineer

## Vai trò và mục tiêu
Bạn phụ trách **một frontend React PWA** chạy trên Safari iPhone, Chrome Android và desktop. Có hai giao diện theo quyền: **Driver** (camera, bắt đầu/kết thúc, nhận cảnh báo) và **Admin** (sau MVP: dashboard tài xế/chuyến đi/sự kiện). Không trực tiếp chạy mô hình AI, không xử lý video trên cloud và không viết backend inference.

## Công nghệ
React + TypeScript + Vite, Tailwind CSS, vite-plugin-pwa, browser `navigator.mediaDevices.getUserMedia`, WebSocket API, React Router, Recharts (giai đoạn dashboard), IndexedDB nếu cần hàng đợi metadata offline. Ưu tiên tối giản dependency.

## Nhiệm vụ theo thứ tự
**F1 – Driver Camera MVP:** responsive/mobile-first; trang chủ với nút `Bắt đầu giám sát` / `Kết thúc`; kiểm tra quyền camera, sử dụng camera trước `facingMode: user`, xem preview, hiển thị thời lượng, chất lượng kết nối. Chỉ bắt đầu khi người dùng chủ động nhấn nút. Khi tab ẩn, màn hình khóa, camera stop hoặc WebSocket rớt → trạng thái `MONITORING_UNAVAILABLE` rõ ràng.

**F2 – Truyền frame:** chụp frame vào canvas, resize/nén JPEG, gửi WebSocket theo schema chung. MVP 3–5 FPS để thử kết nối, giới hạn kích thước/tốc độ, không làm tắc main thread. Nhận kết quả có session/frame/timestamp; bỏ kết quả sai phiên, frame cũ hoặc quá hạn. Không phát cảnh báo bằng dữ liệu `mock-v0` giả như thật.

**F3 – Cảnh báo:** âm thanh dễ nghe do trang đã được người dùng kích hoạt, UI trạng thái rõ ràng; hỗ trợ mute khi đang thử nghiệm, ghi nhật ký lỗi kết nối. Không yêu cầu tài xế chạm/navigating điện thoại khi phương tiện di chuyển. Không cam kết âm thanh/camera chạy khi iOS Safari/PWA vào nền.

**F4 – Admin Dashboard (sau backend/database):** đăng nhập, danh sách tài xế, chuyến đi, sự kiện, bộ lọc trạng thái, chart số cảnh báo trên **giờ giám sát hợp lệ**; xác nhận sự kiện đã xem. Chỉ lấy dữ liệu qua API có phân quyền; không hiển thị video mặt trừ khi có quy trình đồng ý và bảo vệ phù hợp.

## Thiết kế UX cần có
- Màn hình `Không có quyền camera`, `Không tìm thấy camera`, `Mất server`, `Đang thử kết nối`, `Giám sát không khả dụng`.
- Ở `Bắt đầu`: kiểm tra HTTPS/secure context; trên iPhone Safari camera cần quyền và trang phải đang hoạt động.
- Giao diện không gây phân tâm, cảnh báo chủ yếu bằng âm thanh; hành động cài đặt trước khi lái; demo chỉ thử khi xe dừng hoặc dùng video mô phỏng.
- Service Worker dùng cache tài sản UI, **không** cố chạy camera ở nền.

## Bàn giao cần có
- `frontend/` với hướng dẫn setup/build/lint.
- `frontend/src/features/driver/`: giao diện và camera.
- `frontend/src/services/monitorSocket.ts`: kết nối WS theo API contract.
- `frontend/src/features/admin/`: stub hoặc dashboard sau M3.
- UI mock độc lập được bằng `mock analysis_result`; mock phải gắn `model_version=mock-v0`, nhãn rõ demo.
- Test trên Safari iPhone và Chrome Android: quyền camera, tab ẩn, khóa màn, mạng yếu, reconnect, âm thanh.

## Tiêu chí nghiệm thu milestone frontend đầu
1. Chạy trên localhost máy tính và HTTPS địa chỉ thử nghiệm cho điện thoại thật.
2. Camera trước hiển thị sau thao tác người dùng; dừng camera giải phóng tracks.
3. WebSocket gửi đúng frame schema và nhận `NOT_EVALUATED` mock.
4. Có trạng thái mất giám sát, không báo `NORMAL` khi không có kết quả AI.
5. Không bắt đầu Admin Dashboard trước khi luồng PWA↔FastAPI ổn định.

## Bối cảnh chung và hợp đồng tích hợp (PHẢI TUÂN THỦ)
- Dự án: **PREDRIVE AI**, bản MVP nghiên cứu hệ thống giám sát dấu hiệu buồn ngủ/mất tập trung của tài xế.
- Một website **PWA** chạy trên Safari iPhone và Chrome Android; AI **chạy tập trung trên Python server**, không chạy mô hình nhận diện trên trình duyệt.
- Luồng chính: `Camera PWA → WebSocket (WSS khi triển khai) → FastAPI → AI inference → WebSocket result → PWA cảnh báo`; backend lưu sự kiện; admin dashboard ở giai đoạn tiếp theo.
- Chỉ thử với video ghi sẵn, mô phỏng hoặc người tham gia khi phương tiện đứng yên. Không xem MVP là thiết bị an toàn được chứng nhận. Camera/JavaScript có thể dừng khi khóa màn hình hoặc chuyển tab; luôn báo `MONITORING_UNAVAILABLE` khi không còn giám sát đáng tin cậy.
- **Không gọi nhận diện mắt nhắm là dự đoán sớm buồn ngủ**. Các nhãn/độ tin cậy chỉ có ý nghĩa sau khi được huấn luyện, hiệu chỉnh và đánh giá với dữ liệu phù hợp.
- Kết quả phải gắn `session_id`, `frame_id`, `captured_at`, `processed_at`, `model_version`; frontend bỏ kết quả hết hạn/không đúng phiên và không phát cảnh báo từ frame cũ.
- Không đưa credentials, token Telegram, video riêng tư, dữ liệu mặt hay `.env` chứa bí mật lên Git. Mặc định không lưu video thô lên server. Dữ liệu sinh trắc chỉ lưu khi có đồng ý rõ ràng, phạm vi và thời hạn lưu xác định.

### Giao thức chung MVP v0.1 (freeze trước khi tích hợp)
**WebSocket:** `/ws/monitor?session_id=<uuid>` trong môi trường phát triển có kiểm soát; trước khi đưa lên Internet phải thêm xác thực người dùng/phiên và kiểm tra quyền. Client tạo session bằng `POST /api/v1/sessions` (MVP có thể dùng một tài khoản thử nghiệm, không hardcode thông tin tài xế thực).

MVP truyền mỗi frame bằng **một message JSON** chứa JPEG base64 để dễ debug; giới hạn kích thước/fps, server giải mã an toàn. Sau MVP mới cân nhắc binary frames hoặc WebRTC. Chỉ gửi 3–5 FPS trong thử kết nối, **không tuyên bố đủ để phát hiện hành vi chớp mắt ngắn hoặc giám sát an toàn thực tế**.

Client → Server (frame):
```json
{
  "type": "frame",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "frame_id": 12,
  "captured_at": "2026-11-02T03:00:00.000Z",
  "image_format": "jpeg",
  "image_base64": "<base64-jpeg>"
}
```
Server → Client (khi chưa tích hợp AI):
```json
{
  "type": "analysis_result",
  "session_id": "550e8400-e29b-41d4-a716-446655440000",
  "frame_id": 12,
  "captured_at": "2026-11-02T03:00:00.000Z",
  "processed_at": "2026-11-02T03:00:00.120Z",
  "model_version": "mock-v0",
  "state": "NOT_EVALUATED",
  "alert_level": "NONE",
  "face_visible": null,
  "image_quality": "UNKNOWN",
  "risk_score": null,
  "processing_ms": 25
}
```
**Enum nhất quán:**
- `state`: `NOT_EVALUATED | NORMAL | DISTRACTED | DROWSINESS_SIGNS | CRITICAL | MONITORING_UNAVAILABLE`.
- `alert_level`: `NONE | INFO | WARNING | CRITICAL`.
- `image_quality`: `GOOD | LOW_LIGHT | BLURRY | TOO_DARK | UNKNOWN`.
- `risk_score`: `null` đến khi có mô hình đã được hiệu chỉnh; nếu có phải trong `[0,1]`, tuyệt đối không coi như xác suất đã chứng minh khi chưa calibrate.
- Trạng thái `MONITORING_UNAVAILABLE` phải đi kèm **lý do kỹ thuật** như `camera_denied`, `camera_stopped`, `network_lost`, `stale_result`, `server_error` trong thông báo trạng thái riêng, không đánh đồng với buồn ngủ.
- Giờ dùng ISO 8601 UTC; mọi sự kiện có ID bất biến; backend không tin metadata định danh người lái do client tự khai khi triển khai thật.

**Hợp đồng Python nội bộ AI ↔ Backend:**
```python
# Interface minh họa, AI và Backend chốt kiểu cụ thể cùng nhau
async def analyze_frame(frame_bgr, *, session_id: str, frame_id: int, captured_at: str) -> dict:
    # trả các trường: state, alert_level, face_visible,
    # image_quality, risk_score, model_version
    ...
```
**Phân quyền làm việc:** TV1 sở hữu `ai/`, TV2 sở hữu `frontend/`, TV3 sở hữu `backend/` và `database/`. Thay đổi API/enum phải qua `docs/api-contract.md` và cả nhóm thống nhất trước. Nhánh làm việc `feature/ai-model`, `feature/frontend`, `feature/backend`; không tự sửa code vùng người khác khi chưa trao đổi.

## Prompt bắt đầu cho Codex (TV2)
Hãy đọc `FRONTEND_CONTEXT.md` và `docs/api-contract.md` (nếu có). Chỉ xây F1 và F2: responsive PWA, camera trước, Start/Stop, gửi JPEG base64 qua WebSocket, hiển thị trạng thái kết nối và phản hồi mock. Dựng abstraction để sau này có admin dashboard nhưng chưa triển khai admin thật. Đảm bảo xử lý page hidden/camera stop/mất kết nối; không tuyên bố nhận diện AI đang hoạt động. Báo cáo cách test Safari iPhone/Chrome Android.

---

## Cập nhật Milestone M2.5 (08/11/2026) — Mobile App Android + On-Device AI + Giao diện Grab Vẹt Xanh
- **Trạng thái:** Đã hoàn thành và đóng gói thành công file [`PreDrive-debug.apk`](file:///D:/CDIO4/PreDrive-debug.apk).
- **Kiến trúc mới trong `frontend/`:**
  - **Giao diện chính (`src/features/driver/DriverScreen.tsx`):** Thiết kế tối giản theo phong cách Grab (`#00B14F`, font `Be Vietnam Pro` offline), camera toàn màn hình, viên trạng thái góc trên trái, thẻ thông báo dưới viên trạng thái, và thanh đáy gồm 3 nút: `Âm thanh` — `Bắt đầu / Dừng giám sát` — `Đổi cam` (chuyển camera trước/sau trong `src/hooks/useCamera.ts`).
  - **Mascot Vẹt xanh phụ xe (`src/components/ParrotMascot.tsx`):** Vẽ tay bằng SVG phẳng, núp ở mép phải màn hình, chỉ thò đầu nhẹ khi cảnh báo (`warn`) và báo động đỏ (`alarm`).
  - **Chuông báo kim loại (`src/hooks/useBellAlarm.ts`):** Tổng hợp bằng Web Audio API (3 hồi *"reng-reng-reng"*, lặp lại mỗi 1.5s khi `CRITICAL`).
  - **AI chạy trực tiếp trên thiết bị (`src/ai/driverAnalyzer.ts` & `src/hooks/useDriverAI.ts`):** Sử dụng `@mediapipe/tasks-vision` (WASM + `face_landmarker.task` được chép vào `public/` qua `scripts/copy-ai-assets.mjs`), giữ nguyên ngưỡng `EAR = 0.28`, `1.0s` / `2.0s` nhắm mắt, `1.8s` quay đầu và kiểm tra độ sáng `< 20` (`TOO_DARK`).
  - **Android Capacitor (`frontend/android/` & `capacitor.config.ts`):** Cấu hình quyền `CAMERA` trong `AndroidManifest.xml` và tự động cấp quyền camera cho WebView trong `MainActivity.java`.
