# CONTEXT 01 – AI / Deep Learning Engineer

## Vai trò và mục tiêu
Bạn phụ trách **pipeline AI phía server** cho PREDRIVE AI: từ baseline có thể kiểm thử đến mô hình Deep Learning nhận biết dấu hiệu buồn ngủ/mất tập trung, sau đó nghiên cứu thiếu sáng và dự đoán sớm. **Không** phụ trách camera web, UI, API/DB hay gửi Telegram.

## Công nghệ
Python 3.11+ (tùy tương thích thư viện), OpenCV, NumPy, MediaPipe (nếu phiên bản hỗ trợ môi trường), PyTorch, scikit-learn; experiment tracking bằng CSV/JSON hoặc MLflow khi thật sự cần. Model weights nằm ngoài Git nếu quá lớn; ghi nguồn/training config/seed/checksum.

## Nhiệm vụ theo thứ tự
**A1 – Baseline:** module nhận numpy BGR frame, kiểm tra chất lượng, phát hiện khuôn mặt và đặc trưng mắt/đầu. Khi chưa có mô hình kiểm định, output chỉ mô tả dấu hiệu quan sát được; phân biệt `NOT_EVALUATED` và `MONITORING_UNAVAILABLE`. Không tùy tiện gắn nhãn drowsy từ EAR nếu chưa có ngưỡng/kiểm thử rõ ràng.

**A2 – Evaluation:** kiểm tra dataset NTHU-DDD, RLDD và nguồn phù hợp (license, nhãn, thời điểm, video RGB/NIR); chia train/val/test theo **người tham gia hoặc phiên độc lập**, tránh rò rỉ frame/video. So sánh với EAR baseline bằng Precision, Recall, F1, confusion matrix, false alarms/hour, độ trễ, FPS; báo cáo nhóm ban ngày/thiếu sáng riêng. Không tự bịa Accuracy.

**A3 – Deep Learning:** thử MobileNetV3/nhánh CNN nhỏ để trích xuất biểu hiện khuôn mặt; thử GRU hoặc TCN cho dữ liệu chuỗi thời gian. Chỉ triển khai `Early Prediction` khi có nhãn tương lai đúng nghĩa và đánh giá `lead time`, false alarms/hour trên người chưa gặp.

**A4 – Low Light:** đối chứng 3 hướng `ảnh gốc vs CLAHE vs Zero-DCE++`; thử augmentation ánh sáng, đánh giá có tăng **hiệu quả downstream detection** hay không, không mặc định ảnh sáng hơn là chính xác hơn. Nếu quá tối thì trả `image_quality=TOO_DARK`, không tự đoán chắc chắn.

## Bàn giao cần có
- `ai/inference/` có API Python rõ ràng, không phụ thuộc FastAPI/React.
- `ai/training/` notebook/script và cách tái lập train.
- `ai/evaluation/` script + báo cáo metric (kèm dataset/split/seed).
- `ai/tests/` kiểm thử ảnh không có mặt, frame lỗi, ban đêm, đeo kính, góc nghiêng.
- `ai/README.md`: hướng dẫn môi trường, chạy mẫu local, giới hạn.
- `ai/model_card.md`: nhiệm vụ, dữ liệu, metric, giới hạn, phiên bản.

## Tiêu chí nghiệm thu milestone AI đầu
1. Có hàm `analyze_frame(...)` chạy được với frame/ảnh thử nghiệm.
2. Có kiểm thử không crash với ảnh tối, ảnh hỏng và không có mặt.
3. Có kết quả đánh giá thực tế trên video/ảnh mẫu; chưa đủ nhãn thì nêu rõ không đánh giá được Accuracy.
4. Trả dữ liệu theo enum/schema chung để backend dùng được.
5. Không mở rộng lên CNN/Zero-DCE++ trước khi baseline và giao diện tích hợp ổn định.

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

## Prompt bắt đầu cho Codex (TV1)
Hãy đọc `AI_CONTEXT.md` và `docs/api-contract.md` (nếu tồn tại), kiểm tra repository rồi chỉ thực hiện A1: tạo module AI inference độc lập và các test cho đầu vào lỗi/thiếu sáng/không có mặt. Không tuyên bố dự đoán sớm hoặc độ chính xác chưa đo. Trước khi viết code hãy liệt kê file sẽ tạo và interface để backend tích hợp. Sau khi làm xong, báo cáo cách chạy và cập nhật `ai/README.md`.
