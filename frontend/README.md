# PREDRIVE AI — TÀI LIỆU BÀN GIAO FRONTEND PWA (MVP v0.1)

> **Dự án:** PREDRIVE AI — Hệ thống AI giám sát dấu hiệu buồn ngủ và mất tập trung của tài xế  
> **Phân hệ phụ trách:** Frontend / Progressive Web App (PWA)  
> **Thành viên phụ trách:** Kenneth (Frontend / PWA Engineer)  
> **Phiên bản:** MVP v0.1 (Milestone F1 + F2 — Cockpit Focus Mode & Ready-for-Integration)  
> **Ngày cập nhật:** Tháng 11/2026  

---

## MỤC LỤC
1. [Giới thiệu Dự án & Phạm vi Frontend](#1-giới-thiệu-dự-án--phạm-vi-frontend)
2. [Kiến trúc Hệ thống & Vai trò của Frontend](#2-kiến-trúc-hệ-thống--vai-trò-của-frontend)
3. [Tech Stack & Thư viện Chính](#3-tech-stack--thư-viện-chính)
4. [Yêu cầu Môi trường](#4-yêu-cầu-môi-trường)
5. [Cấu trúc Thư mục & Giải thích Module](#5-cấu-trúc-thư-mục--giải-thích-module)
6. [Hướng dẫn Cài đặt & Khởi chạy (Từ file ZIP giải nén)](#6-hướng-dẫn-cài-đặt--khởi-chạy-từ-file-zip-giải-nén)
7. [Hướng dẫn Build Production & Kiểm tra Linter](#7-hướng-dẫn-build-production--kiểm-tra-linter)
8. [Danh mục Tính năng đã Hoàn thành & Kiểm thử](#8-danh-mục-tính-năng-đã-hoàn-thành--kiểm-thử)
9. [Hướng dẫn Sử dụng Chi tiết](#9-hướng-dẫn-sử-dụng-chi-tiết)
10. [Kiểm tra Responsive Desktop / Mobile](#10-kiểm-tra-responsive-desktop--mobile)
11. [Giao thức Tích hợp Backend (REST & WebSocket API Contract v0.1)](#11-giao-thức-tích-hợp-backend-rest--websocket-api-contract-v01)
12. [Cơ chế Demo Mock Mode & Tính Minh bạch AI](#12-cơ-chế-demo-mock-mode--tính-minh-bạch-ai)
13. [Ràng buộc Kỹ thuật PWA, Quyền Camera & Thiết bị Di động](#13-ràng-buộc-kỹ-thuật-pwa-quyền-camera--thiết-bị-di-động)
14. [Kế hoạch Phối hợp Tiếp theo với Backend & AI](#14-kế-hoạch-phối-hợp-tiếp-theo-với-backend--ai)
15. [Xử lý Sự cố Thường gặp (Troubleshooting)](#15-xử-lý-sự-cố-thường-gặp-troubleshooting)

---

## 1. Giới thiệu Dự án & Phạm vi Frontend

### 1.1. Tầm nhìn Dự án PREDRIVE AI
**PREDRIVE AI** là hệ thống nghiên cứu giám sát trạng thái tài xế theo thời gian thực nhằm phát hiện sớm các dấu hiệu buồn ngủ (nhắm mắt kéo dài, gục đầu) và mất tập trung (lệch hướng nhìn, quay đầu bất thường) khi điều khiển phương tiện ô tô (xe con, xe khách, xe tải, container).

### 1.2. Phạm vi Trách nhiệm Frontend (Kenneth)
Frontend được xây dựng dưới dạng **Progressive Web App (PWA)**, hoạt động trực tiếp trên trình duyệt máy tính và điện thoại thông minh:
- **Phạm vi hoàn thành (Milestone F1 + F2)**:
  - Giao diện người dùng buồng lái ô tô hiện đại (Premium Automotive Cockpit Dashboard) với Dark Mode có chiều sâu.
  - Tích hợp luồng camera thật của thiết bị qua Web MediaDevices API (`getUserMedia`).
  - Quản lý vòng đời camera an toàn: cấp quyền theo nhu cầu (lazy permission), dừng camera và giải phóng bộ nhớ sạch sẽ khi kết thúc phiên.
  - Điều phối và đóng gói khung hình (Frame Capture) thành định dạng JSON nén JPEG base64 ở tốc độ 4 FPS (3–5 FPS theo hợp đồng MVP v0.1).
  - Tích hợp sẵn REST Client tạo phiên (`POST /api/v1/sessions`) và WebSocket Client truyền nhận dữ liệu hai chiều (`/ws/monitor?session_id=...`).
  - Chế độ **Camera Focus Mode** toàn màn hình với thuật toán khóa tỷ lệ video thực tế (`aspectRatio`), nút thoát `Esc` và nút dừng khẩn cấp.
  - Cơ chế **Demo Mock Mode** độc lập minh bạch, hiển thị chuẩn xác `NOT_EVALUATED` và `mock-v0` khi Backend chưa kết nối.
  - Hệ thống cảnh báo âm thanh tổng hợp bằng Web Audio API kèm tính năng Mute.
  - Stub giao diện Admin phục vụ lộ trình mở rộng sau này (Milestone F4).
- **Phạm vi không thuộc Frontend**:
  - Không huấn luyện hay chạy mô hình suy luận AI trực tiếp trên trình duyệt (mô hình AI do TV1 chạy tập trung trên server Python).
  - Không lưu trữ video thô hoặc cơ sở dữ liệu trên client.

---

## 2. Kiến trúc Hệ thống & Vai trò của Frontend

```text
[ Thiết bị Tài xế: Laptop / Phone Chrome / iPhone Safari ]
                       │
       ┌───────────────┴───────────────┐
       ▼                               ▼
 [ Camera Sensor ]             [ PWA Frontend ]
 getUserMedia(front-cam)       React 19 + TypeScript + Vite
       │                               │
       │ Khung hình JPEG base64        │ REST POST /api/v1/sessions
       │ (4 FPS, max 480px)            │ WSS /ws/monitor?session_id=...
       └───────────────┬───────────────┘
                       │
                       ▼ WebSocket JSON
             [ FastAPI AI Gateway ] (TV3)
             Session & Rate Limit Validation
                       │
                       ▼ BGR Frame NumPy
             [ Python AI Engine ] (TV1)
             Eye closure (EAR), Head Pose, Face Mesh
                       │
                       ▼ JSON: Analysis Result
             [ PWA Frontend ]
             Hiển thị trạng thái buồng lái & Cảnh báo âm thanh
```

**Vai trò cốt lõi**: Frontend đóng vai trò là "Cockpit Terminal" (trạm buồng lái), thu nhận hình ảnh quang học từ tài xế, mã hóa và truyền tải lên máy chủ thông qua giao thức mạng tốc độ cao, đồng thời lập tức phát cảnh báo nghe nhìn khi máy chủ phát hiện nguy cơ.

---

## 3. Tech Stack & Thư viện Chính

| Công nghệ | Phiên bản | Vai trò & Mục đích sử dụng |
|---|---|---|
| **React** | `^19.3.1` | Thư viện UI cốt lõi, quản lý component state và rendering hiệu năng cao. |
| **TypeScript** | `~7.0.2` | Đảm bảo tính an toàn kiểu dữ liệu (Strict Type Safety), tuân thủ `verbatimModuleSyntax`. |
| **Vite** | `^8.3.5` | Build tool và Dev Server thế hệ mới với Hot Module Replacement (HMR) tức thì. |
| **Tailwind CSS** | `^3.4.19` | Framework CSS atomic tùy biến màu sắc buồng lái ô tô hiện đại (`automotive-dark`, `cyan`). |
| **Lucide React** | `^1.66.0` | Bộ icon SVG công nghệ cao, đồng bộ thị giác. |
| **vite-plugin-pwa** | `^2.0.0` | Tự động sinh Service Worker (`workbox`), Web App Manifest cho cài đặt PWA trên di động. |
| **Oxlint** | `^1.89.0` | Bộ linter siêu tốc kiểm soát chất lượng mã nguồn TypeScript/React. |

> **Cam kết tối giản**: Ứng dụng không sử dụng bất kỳ UI kit cồng kềnh nào từ bên ngoài nhằm tối ưu tối đa tốc độ tải trang, giảm độ trễ và tiết kiệm pin thiết bị di động.

---

## 4. Yêu cầu Môi trường

Trước khi cài đặt, hãy đảm bảo máy tính đã cài đặt:
- **Node.js**: Phiên bản `18.0.0` trở lên (Khuyến nghị **v20 LTS** hoặc **v22 LTS**).
- **npm**: Phiên bản `9.0.0` trở lên (đi kèm Node.js).
- **Trình duyệt**: Google Chrome 100+, Microsoft Edge 100+, Mozilla Firefox 100+, hoặc Apple Safari 15+.
- **Phần cứng**: Máy tính hoặc điện thoại có webcam/camera trước hoạt động bình thường.

Kiểm tra phiên bản bằng dòng lệnh:
```bash
node -v
npm -v
```

---

## 5. Cấu trúc Thư mục & Giải thích Module

```text
D:\predrive-ai\frontend\
├── public/                       # Tài nguyên tĩnh độc lập
│   ├── favicon.svg               # Biểu tượng radar PREDRIVE AI
│   ├── pwa-192x192.svg           # Icon ứng dụng PWA kích thước 192px
│   └── pwa-512x512.svg           # Icon ứng dụng PWA kích thước 512px
├── src/
│   ├── config/
│   │   └── env.ts                # Cấu hình biến môi trường, FPS (4 FPS), kích thước frame (480px)
│   ├── types/
│   │   └── monitor.ts            # Khai báo TypeScript types chuẩn API Contract v0.1
│   ├── services/
│   │   ├── api.ts                # REST client tạo session (POST /api/v1/sessions)
│   │   └── monitorSocket.ts      # WebSocket client quản lý vòng đời WS và lọc frame quá hạn (stale)
│   ├── hooks/
│   │   ├── useCamera.ts          # Hook điều khiển webcam thật, xin quyền, nén JPEG, bắt visibilitychange
│   │   ├── useMonitorSocket.ts   # Hook điều phối streaming 4 FPS, đo RTT Latency, quản lý Mock Demo Mode
│   │   ├── useSessionTimer.ts    # Hook đếm thời gian phiên giám sát (HH:MM:SS)
│   │   └── useAlertSound.ts      # Hook tổng hợp âm thanh cảnh báo bằng Web Audio API kèm toggle Mute
│   ├── components/
│   │   ├── Header.tsx            # Thanh điều hướng tích hợp buồng lái, badge server, Mute, Diagnostics
│   │   ├── CameraPreview.tsx     # Khung xem webcam thật, Focus Mode toàn màn hình, Face Guide khóa tỷ lệ
│   │   ├── MonitoringControls.tsx# Cụm điều khiển chính: Nút Bắt đầu / Kết thúc và Đồng hồ thời lượng phiên
│   │   ├── StatusBadge.tsx       # Bảng trạng thái an toàn AI và lý do lỗi kỹ thuật
│   │   ├── DiagnosticsPanel.tsx  # Bảng chẩn đoán kỹ thuật Telemetry (FPS, RTT, Frame sent/received)
│   │   └── Footer.tsx            # Disclaimer an toàn và thông tin đồ án
│   ├── features/
│   │   ├── driver/
│   │   │   └── DriverMonitor.tsx # Màn hình giám sát tài xế (bố cục 2 cột Desktop & 1 cột Mobile)
│   │   └── admin/
│   │       └── AdminStub.tsx     # Giao diện mẫu Admin chuẩn bị cho Milestone F4 sau này
│   ├── App.tsx                   # Root component điều phối view Tài xế / Quản trị
│   ├── main.tsx                  # Điểm khởi động ứng dụng React (React 19 StrictMode)
│   └── index.css                 # Import Tailwind CSS, Dark Mode gradient buồng lái
├── index.html                    # File HTML gốc với viewport di động viewport-fit=cover
├── package.json                  # Khai báo dependency và scripts
├── tsconfig.json                 # Cấu hình TypeScript gốc
├── tsconfig.app.json             # Cấu hình compiler options cho ứng dụng (verbatimModuleSyntax: true)
├── vite.config.ts                # Cấu hình Vite dev server (host: 0.0.0.0:5173) và PWA manifest
└── tailwind.config.js            # Bảng màu buồng lái ô tô hiện đại (automotive dark theme)
```

---

## 6. Hướng dẫn Cài đặt & Khởi chạy (Từ file ZIP giải nén)

Sau khi nhận và giải nén file `frontend.zip` (hoặc toàn bộ dự án `predrive-ai`):

### Bước 1: Mở Terminal tại thư mục `frontend`
```bash
cd D:\predrive-ai\frontend
```

### Bước 2: Cài đặt các thư viện cần thiết
```bash
npm install
```
> *Lưu ý*: Quá trình cài đặt mất khoảng 10–30 giây tùy thuộc tốc độ mạng. Sau khi hoàn tất sẽ xuất hiện thư mục `node_modules`.

### Bước 3: Khởi động Development Server
```bash
npm run dev
```

Terminal sẽ hiển thị thông báo sẵn sàng:
```text
  VITE v8.x.x  ready in 250 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: http://192.168.x.x:5173/
  ➜  press h + enter to show help
```

### Bước 4: Mở trình duyệt kiểm tra
Mở trình duyệt Google Chrome hoặc Edge và truy cập: **`http://localhost:5173/`**

---

## 7. Hướng dẫn Build Production & Kiểm tra Linter

### 7.1. Kiểm tra Linter bằng Oxlint
Để rà soát lỗi cú pháp, kiểu dữ liệu và chất lượng code:
```bash
npm run lint
```
*Kết quả chuẩn*: `Found 0 warnings and 0 errors.`

### 7.2. Biên dịch Production Build
Trước khi bàn giao hoặc đưa lên máy chủ web:
```bash
npm run build
```
Lệnh này sẽ tự động chạy:
1. `tsc -b`: Trình biên dịch TypeScript kiểm tra type-safety toàn diện.
2. `vite build`: Tối ưu hóa CSS, đóng gói JavaScript thành các chunk tối ưu.
3. `vite-plugin-pwa`: Tự động khởi tạo Service Worker `dist/sw.js` và `manifest.webmanifest`.

Thư mục đầu ra sẵn sàng triển khai là: `D:\predrive-ai\frontend\dist\`.

### 7.3. Xem thử bản Production cục bộ (Preview)
```bash
npm run preview
```
Trình duyệt mở tại `http://localhost:4173/` để kiểm tra bản build thực tế.

---

## 8. Danh mục Tính năng đã Hoàn thành & Kiểm thử

| STT | Nhóm Chức năng | Trạng thái | Chi tiết triển khai & Kiểm chứng |
|---|---|---|---|
| 1 | **UI Cockpit Dark Theme** | Hoàn thành | Tông màu xanh đen buồng lái ô tô cao cấp (`#070A12`), điểm nhấn Electric Cyan. |
| 2 | **Webcam Thật (`getUserMedia`)** | Hoàn thành | Mặc định camera trước (`facingMode: 'user'`), phân giải tối ưu 640x480. |
| 3 | **Cấp quyền theo nhu cầu** | Hoàn thành | Camera chỉ bật khi nhấn "Bắt đầu giám sát", không tự động xin quyền gây phiền. |
| 4 | **Giải phóng Phần cứng An toàn** | Hoàn thành | Dừng toàn bộ tracks (`track.stop()`) khi dừng hoặc đóng trang; đèn camera tắt ngay. |
| 5 | **Phát hiện Gián đoạn Giám sát**| Hoàn thành | Bắt sự kiện `visibilitychange` khi tab bị ẩn hoặc tắt màn hình → chuyển `MONITORING_UNAVAILABLE`. |
| 6 | **Camera Focus Mode** | Hoàn thành | Chế độ xem phóng to toàn màn hình, khóa đúng tỷ lệ video thực (`aspectRatio`), không lọt vào vùng đen letterbox. |
| 7 | **Face Alignment Guide** | Hoàn thành | Khung căn chỉnh khuôn mặt nét mảnh, có nút Eye bật/tắt nhanh; không giả lập landmark AI. |
| 8 | **Đồng hồ Thời lượng Phiên** | Hoàn thành | Đếm thời lượng thực tế (HH:MM:SS), tự reset khi dừng phiên. |
| 9 | **Nén & Giới hạn Tần số Frame**| Hoàn thành | Canvas resize tối đa 480px, nén JPEG quality 0.65, điều tiết chuẩn 4 FPS. |
| 10 | **WebSocket Protocol Client** | Hoàn thành | Đóng gói JSON frame theo contract, lọc frame cũ (`frame_id`), bỏ frame quá hạn (`stale`). |
| 11 | **Cơ chế Demo Mock v0** | Hoàn thành | Tự động kích hoạt khi Backend chưa chạy, trả `NOT_EVALUATED` minh bạch, không giả kết quả AI. |
| 12 | **Cảnh báo Âm thanh** | Hoàn thành | Web Audio API tổng hợp âm beep phân tầng (Info, Warning, Critical) kèm nút Mute. |
| 13 | **Bảng Telemetry Chẩn đoán** | Hoàn thành | Hiển thị Target FPS vs Actual FPS, RTT Latency, Frame đếm, Session UUID. |
| 14 | **Responsive Toàn diện** | Hoàn thành | Bố cục 2 cột thông minh trên Desktop và 1 cột tối ưu trên Mobile (360px–430px). |
| 15 | **Admin Stub** | Hoàn thành | Giao diện chuẩn bị cho Milestone F4, cấu trúc sẵn sàng kết nối DB/Auth sau này. |

---

## 9. Hướng dẫn Sử dụng Chi tiết

### 9.1. Bắt đầu và Dừng Phiên Giám sát
1. Nhấn nút **"BẮT ĐẦU GIÁM SÁT"** màu Cyan trên màn hình.
2. Trình duyệt xuất hiện thông báo xin quyền: Nhấn **"Cho phép" (Allow)**.
3. Luồng camera thật hiển thị ngay lập tức:
   - Đèn báo **`LIVE CAMERA`** màu xanh lá sáng nhấp nháy cùng chỉ số FPS thực tế.
   - Đồng hồ thời lượng phiên bắt đầu đếm (`00:01`, `00:02`...).
   - Thẻ trạng thái hiển thị: *"Camera đang hoạt động ở chế độ demo cục bộ. Chưa kết nối máy chủ AI và chưa có kết quả phân tích."*
4. Khi muốn kết thúc: Nhấn **"KẾT THÚC GIÁM SÁT"** màu đỏ:
   - Camera được giải phóng hoàn toàn (đèn webcam trên laptop tắt ngay).
   - Đồng hồ dừng lại và đặt về `00:00`.
   - Trạng thái quay về `IDLE` (Chờ khởi động).

### 9.2. Sử dụng Chế độ Phóng to (Focus Mode)
- **Kích hoạt**: Nhấn nút biểu tượng **Phóng to (`Maximize2`)** ở góc trên bên phải khung camera.
- **Trải nghiệm trong Focus Mode**:
  - Camera mở rộng chiếm trọn vùng nhìn màn hình với nền mờ buồng lái.
  - Video được căn giữa bằng `object-contain`, không bị crop mất trán hoặc cằm.
  - Khung Face Alignment Guide được tự động khóa vừa vặn trên bề mặt video, không tràn vào khoảng đen trên/dưới.
  - Nhấn nút hình **Con mắt (Eye)** trên thanh công cụ để ẩn/hiện khung căn chỉnh.
  - Khi cần dừng khẩn cấp: Nút **"KẾT THÚC GIÁM SÁT"** màu đỏ nằm sẵn ở thanh dưới cùng.
- **Thu nhỏ**: Nhấn nút **"Thu nhỏ"** hoặc nhấn phím **`Escape`** trên bàn phím: Giao diện trở về dashboard bình thường, webcam và timer vẫn tiếp tục chạy mượt mà.

### 9.3. Bật/Tắt Âm thanh & Xem Bảng Chẩn đoán (Telemetry)
- **Nút Loa (Mute/Unmute)**: Nằm ở góc trên Header. Nhấn để bật hoặc tắt âm thanh cảnh báo trong quá trình thử nghiệm.
- **Nút Nhịp tim (Activity - Diagnostics)**: Nhấn để mở bảng thông số kỹ thuật (đo FPS thực tế, độ trễ RTT mili-giây, số lượng frame đã gửi và nhận).

---

## 10. Kiểm tra Responsive Desktop / Mobile

Ứng dụng được thiết kế theo tư duy **Mobile-First Responsive**:

### 10.1. Màn hình Máy tính (Desktop / Laptop >= 1024px)
- **Bố cục 2 Cột Split-Screen**:
  - **Cột Trái (7/12)**: Camera Preview trung tâm với tỷ lệ 16:9 / 16:10, chiều cao giới hạn `max-h-[460px]`, đảm bảo toàn bộ dashboard nằm vừa vặn trong một tầm mắt mà **không cần cuộn chuột**.
  - **Cột Phải (5/12)**: Cụm điều khiển chính (Bắt đầu/Kết thúc) + Thẻ trạng thái AI (Status Badge) đặt ngang tầm mắt với camera.

### 10.2. Màn hình Điện thoại (Mobile 360px – 430px)
- **Header 2 Hàng Tinh Gọn**:
  - Hàng 1: Logo PREDRIVE AI (chữ nằm trên 1 dòng, không bị ngắt) + Tabs Tài xế / Quản trị.
  - Hàng 2: Huy hiệu Server và cụm nút Mute / Diagnostics không bao giờ bị cắt mép.
- **Thanh Trạng thái Tóm tắt (Compact Status Banner)**: Đặt ngay phía trên Camera giúp tài xế quan sát tức thì tình trạng hệ thống mà không cần cuộn trang xuống dưới.
- **Nút bấm kích thước lớn**: Nút điều khiển có chiều cao tối thiểu 48px, thuận tiện thao tác cảm ứng bằng ngón tay cái khi điện thoại gắn trên giá đỡ ô tô.

---

## 11. Giao thức Tích hợp Backend (REST & WebSocket API Contract v0.1)

Frontend đã được thiết kế sẵn sàng 100% để kết nối với Backend FastAPI của thành viên TV3 theo đúng hợp đồng đã chốt trong `docs/api-contract.md` và `PROJECT_CONTEXT.md`:

### 11.1. Cấu hình Địa chỉ Backend
Mặc định trong mã nguồn (`src/config/env.ts`):
- REST API: `http://localhost:8000`
- WebSocket: `ws://localhost:8000/ws/monitor`

Khi Backend chạy ở máy khác hoặc domain khác, chỉ cần tạo file `.env` hoặc `.env.local` tại thư mục `frontend`:
```env
VITE_BACKEND_URL=http://192.168.1.100:8000
VITE_WS_URL=ws://192.168.1.100:8000/ws/monitor
```

### 11.2. Luồng Kết nối Khi Bắt đầu Giám sát
1. **Bước 1 — Tạo phiên REST**:
   Frontend gửi `POST /api/v1/sessions`:
   ```json
   {
     "client_type": "pwa",
     "app_version": "0.1.0-alpha"
   }
   ```
   Backend trả về:
   ```json
   {
     "session_id": "550e8400-e29b-41d4-a716-446655440000",
     "created_at": "2026-11-02T03:00:00.000Z"
   }
   ```

2. **Bước 2 — Mở kết nối WebSocket**:
   Frontend kết nối: `WS /ws/monitor?session_id=550e8400-e29b-41d4-a716-446655440000`

3. **Bước 3 — Client gửi Khung hình (4 FPS)**:
   ```json
   {
     "type": "frame",
     "session_id": "550e8400-e29b-41d4-a716-446655440000",
     "frame_id": 12,
     "captured_at": "2026-11-02T03:00:00.000Z",
     "image_format": "jpeg",
     "image_base64": "<base64-encoded-jpeg>"
   }
   ```

4. **Bước 4 — Server trả Kết quả Phân tích**:
   ```json
   {
     "type": "analysis_result",
     "session_id": "550e8400-e29b-41d4-a716-446655440000",
     "frame_id": 12,
     "captured_at": "2026-11-02T03:00:00.000Z",
     "processed_at": "2026-11-02T03:00:00.120Z",
     "model_version": "baseline-v1",
     "state": "NORMAL",
     "alert_level": "NONE",
     "face_visible": true,
     "image_quality": "GOOD",
     "risk_score": null,
     "processing_ms": 25
   }
   ```

### 11.3. Bảng Enum Trạng thái Thống nhất
- **`state`**:
  - `NOT_EVALUATED`: Đang stream thử kết nối, chưa có AI inference.
  - `NORMAL`: Tài xế tỉnh táo, mắt mở, tập trung nhìn đường.
  - `DISTRACTED`: Lệch hướng nhìn hoặc quay đầu quá thời gian quy định.
  - `DROWSINESS_SIGNS`: Nhắm mắt kéo dài (EAR thấp) hoặc gật đầu.
  - `CRITICAL`: Nguy cơ tai nạn cao, buồn ngủ nghiêm trọng.
  - `MONITORING_UNAVAILABLE`: Không thể giám sát (kèm lý do kỹ thuật).
- **`alert_level`**: `NONE` | `INFO` | `WARNING` | `CRITICAL`.
- **`image_quality`**: `GOOD` | `LOW_LIGHT` | `BLURRY` | `TOO_DARK` | `UNKNOWN`.

---

## 12. Cơ chế Demo Mock Mode & Tính Minh bạch AI

Để hỗ trợ kiểm thử giao diện độc lập mà không cần chờ Backend hoặc mô hình AI hoàn thiện:
- **Tự động Fallback**: Khi người dùng nhấn bắt đầu mà Backend FastAPI chưa chạy, Frontend tự động kích hoạt **Demo Mock Mode** cục bộ.
- **Tính minh bạch tuyệt đối**:
  - Giao diện gắn nhãn rõ ràng: `DEMO MOCK CỤC BỘ` và `Model ID: mock-v0`.
  - Thông báo hiển thị: *"Camera đang hoạt động ở chế độ demo cục bộ. Chưa kết nối máy chủ AI và chưa có kết quả phân tích."*
  - Tuyệt đối không tự bịa ra kết quả AI như `NORMAL` hay phát cảnh báo buồn ngủ giả để đảm bảo tính liêm chính nghiên cứu khoa học.

---

## 13. Ràng buộc Kỹ thuật PWA, Quyền Camera & Thiết bị Di động

1. **Yêu cầu Secure Context (HTTPS)**:
   - Các trình duyệt hiện đại (Chrome Android, Safari iPhone) **chỉ cho phép truy cập webcam thông qua HTTPS hoặc localhost**.
   - Nếu mở website trên điện thoại qua địa chỉ IP mạng nội bộ HTTP (ví dụ `http://192.168.1.15:5173`), trình duyệt sẽ chặn camera với lỗi `insecure_context`.
   - **Giải pháp kiểm thử trên điện thoại**:
     - Sử dụng công cụ tạo đường hầm HTTPS:
       ```bash
       npx localtunnel --port 5173
       # hoặc: ngrok http 5173
       ```
     - Mở đường dẫn HTTPS được cung cấp trên Safari iPhone hoặc Chrome Android.
2. **Hạn chế Chạy nền (Background Limitations)**:
   - Ứng dụng PWA hoạt động trong sandbox trình duyệt. Khi người dùng khóa màn hình điện thoại hoặc chuyển sang ứng dụng khác, trình duyệt sẽ tạm dừng luồng camera để tiết kiệm pin.
   - Khi đó, hệ thống sẽ tự động bắt sự kiện và thông báo: **`MONITORING_UNAVAILABLE (tab_hidden)`**, không giả định tài xế vẫn an toàn.
3. **Cảnh báo An toàn Giao thông**:
   - Đây là bản thử nghiệm nghiên cứu MVP (v0.1), **không phải thiết bị an toàn đã qua kiểm định**.
   - Chỉ được thử nghiệm với xe đang đứng yên hoặc trong phòng thí nghiệm mô phỏng.

---

## 14. Kế hoạch Phối hợp Tiếp theo với Backend & AI

1. **Phối hợp với TV3 (Backend Engineer)**:
   - Kiểm thử kết nối thực tế giữa Frontend và FastAPI: endpoint `POST /api/v1/sessions` và WebSocket `/ws/monitor`.
   - Đo đạc độ trễ mạng thực tế (RTT) trên mạng nội bộ LAN.
   - Thử nghiệm các trường hợp mạng chập chờn, tự động kết nối lại (reconnect).
2. **Phối hợp với TV1 (AI Engineer)**:
   - Tiếp nhận kết quả suy luận thực tế từ mô hình AI (nhận diện nhắm mắt, góc đầu).
   - Kiểm tra hiển thị cảnh báo âm thanh và thị giác khi `alert_level` chuyển sang `WARNING` hoặc `CRITICAL`.
   - Kiểm tra trường hợp môi trường thiếu sáng (`image_quality: LOW_LIGHT`).
3. **Lộ trình Mở rộng Milestone M3 & M4**:
   - Khi Backend hoàn thành hệ thống cơ sở dữ liệu và xác thực (Auth/PostgreSQL), Frontend sẽ nâng cấp **Admin Dashboard** để theo dõi đội xe và tổng số giờ giám sát hợp lệ.

---

## 15. Xử lý Sự cố Thường gặp (Troubleshooting)

### Sự cố 1: Lỗi cổng 5173 bị chiếm dụng (`Port 5173 is already in use`)
- **Nguyên nhân**: Một tiến trình Vite khác đang chạy nền.
- **Khắc phục**:
  Vite sẽ tự động chuyển sang cổng 5174. Bạn chỉ cần mở `http://localhost:5174/`.
  Hoặc dừng tiến trình cũ trên Windows PowerShell:
  ```powershell
  Stop-Process -Name node -Force
  ```

### Sự cố 2: Lỗi không mở được Camera (`camera_denied` hoặc `camera_not_found`)
- **Nguyên nhân**: Trình duyệt bị chặn quyền camera hoặc ứng dụng khác (Zoom, Teams) đang chiếm dụng camera.
- **Khắc phục**:
  1. Kiểm tra biểu tượng chiếc khóa / camera trên thanh địa chỉ trình duyệt, chọn **"Reset permission"** hoặc **"Allow"**.
  2. Tắt các ứng dụng hội nghị trực tuyến đang dùng webcam.
  3. Nhấn nút **"Thử lại quyền camera"** trên giao diện.

### Sự cố 3: Lỗi trên iPhone / Android báo "Yêu cầu kết nối HTTPS" (`insecure_context`)
- **Nguyên nhân**: Mở bằng IP `http://192.168.x.x` không có chứng chỉ SSL.
- **Khắc phục**: Chạy `npx localtunnel --port 5173` để lấy link `https://...` mở trên điện thoại.

### Sự cố 4: Lỗi cài đặt dependency khi chạy `npm install`
- **Nguyên nhân**: Phiên bản Node.js quá cũ (< 18.0.0).
- **Khắc phục**: Cập nhật Node.js lên phiên bản LTS mới nhất (v20 hoặc v22) từ trang chủ [nodejs.org](https://nodejs.org/).

---

*Tài liệu được soạn thảo hoàn chỉnh phục vụ công tác bàn giao và nghiệm thu nội bộ nhóm PREDRIVE AI.*
