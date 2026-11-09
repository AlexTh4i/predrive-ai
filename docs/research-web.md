# Nghiên cứu triển khai Web Admin

## 1. Xác thực SSE

`EventSource` gốc cho phép cấu hình credentials, nhưng constructor không có tùy chọn đặt header. Cookie HttpOnly cần đổi cơ chế xác thực phía backend. Token ngắn hạn trong query cần endpoint cấp token chuyên dụng và xử lý URL trong log. Web chọn `fetch` với Bearer và parser SSE để giữ hợp đồng JWT M3. Trình duyệt đã kiểm tra gửi header và nhận sự kiện qua máy chủ fixture. [WHATWG HTML · Server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html)

## 2. Cảnh báo khi tab ở nền

Mặc định tắt âm báo. Khi người dùng bật, thao tác đó mở Web Audio. Cảnh báo CRITICAL mới sẽ phát chuông nếu audio context đang chạy và tăng bộ đếm ở tiêu đề khi tab ở nền. Tiêu đề trở về mặc định khi tab hiện lại. Notification API cần quyền thông báo và secure context, vì vậy phiên bản này dùng tiêu đề và âm thanh tùy chọn. Trình duyệt hoặc hệ điều hành có thể tạm dừng tab và audio khi chạy nền. [MDN · Web Audio API best practices](https://developer.mozilla.org/en-US/docs/Web/API/Web_Audio_API/Best_practices), [MDN · Notifications API](https://developer.mozilla.org/en-US/docs/Web/API/Notifications_API)

## 3. Gọi và nhắn Zalo

Web chuẩn hóa số nội địa Việt Nam dạng `0xxxxxxxxx` thành `+84xxxxxxxxx`. Liên kết dùng `tel:+84…` và `https://zalo.me/84…` theo đặc tả. Playwright Chromium đã kiểm tra các href. Chưa gọi số thực hoặc xác nhận mở ứng dụng Zalo trên Android/iOS. Trên desktop, `tel:` phụ thuộc vào ứng dụng đã đăng ký xử lý liên kết. Zalo có thể mở trang web hoặc chuyển sang ứng dụng tùy thiết bị, tài khoản và trạng thái cài đặt. [RFC 3966 · The tel URI](https://www.rfc-editor.org/rfc/rfc3966), [Zalo](https://zalo.me/vi/)

## 4. Đội xe 30–50 tài xế

Dashboard đưa CRITICAL lên đầu, sau đó sắp theo mức độ cần chú ý. Bộ lọc trạng thái và tìm nhanh theo tên không dấu hoặc biển số giúp thu hẹp danh sách. Bố cục có ba, hai hoặc một cột. Cột cảnh báo giới hạn năm mục và lịch sử có phân trang. Mock bàn giao chứa sáu tài xế, chưa đo hiệu năng với tải dữ liệu thật của đội xe lớn.

## 5. Khả năng tiếp cận

Trạng thái luôn có nhãn chữ và dấu nhận diện. Cảnh báo nguy hiểm có biểu tượng chuông. Biểu đồ có vùng số liệu có thể mở bằng bàn phím. Menu di động dùng hộp thoại có quản lý focus, form có nhãn và hiệu ứng chuyển động giảm theo thiết lập hệ điều hành. [WCAG 2.2 · Use of Color](https://www.w3.org/WAI/WCAG22/Understanding/use-of-color.html)
