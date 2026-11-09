# PreDrive AI · Web điều hành đội xe

Bảng điều hành tiếng Việt dành cho quản lý và người trực. PreDrive AI hỗ trợ theo dõi và cảnh báo. Tài xế cần tuân thủ quy định an toàn giao thông.

## Chạy thử

Yêu cầu Node.js 20.19+ trong dòng 20 hoặc 22.12 trở lên và npm. Từ gốc repository, chạy:

```powershell
cd admin-web
npm install
npm run dev
```

Mở [http://localhost:5174](http://localhost:5174). Web chạy bằng mock ngay khi chưa có tệp môi trường. Trang đăng nhập có nút điền nhanh tài khoản mô phỏng.

| Tên đăng nhập | Tên hiển thị | Mật khẩu demo | Quyền |
| --- | --- | --- | --- |
| `manager` | Nguyễn Minh Khanh | `predrive123` | Xem, ghi nhận liên hệ, sửa cài đặt |
| `dispatcher` | Huỳnh Tấn Gia Huy | `predrive123` | Xem và ghi nhận liên hệ |

Mock có sáu tài xế hư cấu, lịch sử 28 ngày và trạng thái thay đổi mỗi 4 giây. Cảnh báo nguy hiểm mới đầu tiên xuất hiện sau khoảng 16 giây. Cài đặt, ghi nhận liên hệ và cảnh báo phát sinh được giữ trong phiên của tab khi tải lại. Số điện thoại demo chỉ dùng để minh họa định dạng.

## Các trang

| Đường dẫn | Chức năng |
| --- | --- |
| `/login` | Xác thực tài khoản và phân quyền |
| `/` | Giám sát trực tiếp, ưu tiên nguy hiểm, tìm và lọc tài xế, ghi nhận liên hệ có ghi chú, âm báo tùy chọn, biểu đồ theo giờ |
| `/history` | Lọc theo tài xế, ngày, mức độ, loại và tình trạng liên hệ. Phân trang và đánh dấu sự kiện gửi muộn |
| `/drivers`, `/drivers/:id` | Tìm tài xế, xem hồ sơ và phiên giám sát, xem cảnh báo trên giờ lái, mở liên kết gọi hoặc Zalo |
| `/stats` | Phân bố theo giờ, xu hướng 7 ngày hoặc 4 tuần, xếp hạng và sức khỏe hệ thống |
| `/settings` | Quản lý ngưỡng lái liên tục, số phút nghỉ để đặt lại và chia sẻ vị trí |

## Kết nối backend M3

Sao chép `.env.example` thành `.env.local`, đặt `VITE_USE_MOCK=false`, rồi khởi động lại Vite. Giữ `VITE_API_URL=/api/v1` và đặt `API_PROXY_TARGET` theo máy chủ backend để dùng proxy Vite. Nếu gọi trực tiếp khác origin, đặt `VITE_API_URL` thành URL đầy đủ có đuôi `/api/v1` và cấu hình CORS cho frontend.

Web gửi JWT qua header Bearer cho REST và SSE, kiểm tra phiên qua `GET /auth/me` khi tải lại và yêu cầu đăng nhập lại nếu gặp 401. Hai chế độ dùng cùng interface trong `src/api/contract.ts`. Xem [ghi chú tích hợp](docs/api-integration-notes.md) và [nghiên cứu Web Admin](../docs/research-web.md).

Khi triển khai, build lại với môi trường tương ứng và phục vụ `dist/` qua HTTPS. Nếu dùng URL tương đối, reverse proxy triển khai phải chuyển tiếp `/api/v1` và giữ SSE không bị buffer. Với các đường dẫn giao diện, cấu hình máy chủ trả `index.html` để hỗ trợ mở trực tiếp và tải lại.

## Kiểm tra

```powershell
npm run typecheck
npm run lint
npm run build
npx playwright install chromium
npm test
```

Playwright dùng các cổng 5184–5186 để kiểm tra mock và HTTP/SSE qua máy chủ M3 giả lập. Các kịch bản bao phủ phân quyền, cảnh báo mới, âm báo, ghi chú liên hệ, mất kết nối, heartbeat cũ, lọc lịch sử, giờ Việt Nam, phân trang, hồ sơ, thống kê và cài đặt. Bảy màn hình được kiểm tra ở độ rộng 320, 375, 390, 768, 1366 và 1920 px, gồm kiểm tra cuộn ngang và thao tác menu mobile bằng bàn phím. Backend trong repo hiện có API MVP, nên cần kiểm tra lại với FastAPI M3 khi nhóm bàn giao.

Bản ZIP có thư mục `admin-web/` và các tài liệu liên quan trong `docs/`. Sau khi giải nén, chạy `npm ci` trong `admin-web/` để cài đúng phiên bản trong lockfile rồi dùng `npm run dev`.

## Cấu trúc

- `src/pages/` chứa các màn hình và `src/components/` chứa layout, thẻ, biểu đồ và linh vật sao chép từ app tài xế.
- `src/types.ts` và `src/api/` định nghĩa kiểu dữ liệu và adapter M3.
- `src/hooks/` quản lý phiên đăng nhập, tải dữ liệu và luồng trực tiếp.
- `src/styles/app.css` chứa Tailwind CSS, token màu và bố cục responsive.
