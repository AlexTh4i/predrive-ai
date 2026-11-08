# PREDRIVE AI — AI Baseline Module (v0.1)

> Phân hệ phụ trách: **TV1 (AI / Deep Learning)**  
> Trạng thái: **Milestone A1 Complete** (Tích hợp MediaPipe FaceLandmarker, EAR Drowsiness Detection, Head Pose Distraction, Image Quality Check).

---

## 1. Tổng quan Module AI

Module AI nằm độc lập trong thư mục `ai/`, tiếp nhận khung hình ảnh dạng NumPy BGR (hoặc RGB) từ Backend Gateway thông qua WebSocket, thực hiện:
1. **Kiểm tra chất lượng ảnh (`assess_image_quality`):**
   - Đo độ sáng trung bình (Luminance) $\rightarrow$ phân loại `TOO_DARK` (< 20) hoặc `LOW_LIGHT` (< 45).
   - Đo độ sắc nét (Laplacian variance) $\rightarrow$ phân loại `BLURRY` (< 35) hoặc `GOOD`.
   - Khi gặp ảnh `TOO_DARK` hoặc frame rỗng, trả về `MONITORING_UNAVAILABLE`, không đoán bừa.
2. **Trích xuất đặc trưng khuôn mặt (MediaPipe FaceLandmarker):**
   - Sử dụng model `ai/models/face_landmarker.task` (478 điểm mốc 3D).
   - Landmark mắt trái: `[33, 160, 158, 133, 153, 144]`
   - Landmark mắt phải: `[362, 385, 387, 263, 373, 380]`
3. **Phát hiện dấu hiệu buồn ngủ (EAR - Eye Aspect Ratio):**
   - Tính toán tỷ lệ mở/nhắm mắt dựa trên khoảng cách Euclidean.
   - Ngưỡng nhắm mắt: `EAR < 0.22`.
   - Duy trì bộ đếm thời gian theo từng `session_id`:
     - Nhắm mắt liên tục $\ge$ 1.0s: Cảnh báo `DROWSINESS_SIGNS` (Level `WARNING`).
     - Nhắm mắt liên tục $\ge$ 2.0s: Cảnh báo `CRITICAL` (Level `CRITICAL`).
4. **Phát hiện mất tập trung (Head Pose / Nodding):**
   - Theo dõi tọa độ mốc mũi `landmarks[1]`: phát hiện gục đầu (`y > 0.72`) hoặc quay mặt quá nghiêng (`x < 0.30` hoặc `x > 0.70`).
   - Lệch hướng liên tục $\ge$ 1.8s: Cảnh báo `DISTRACTED` (Level `WARNING`).

---

## 2. Cấu trúc thư mục

```text
ai/
├── __init__.py               # Exports DriverMonitorAI, schemas
├── models/
│   └── face_landmarker.task  # Pretrained MediaPipe Task model
├── inference/
│   ├── __init__.py
│   ├── analyzer.py           # Core DriverMonitorAI class & per-session state
│   └── quality.py            # Hàm assess_image_quality
├── schemas.py                # Pydantic schemas & Enums chuẩn API Contract v0.1
├── tests/
│   └── test_analyzer.py      # Unit tests (ảnh đen, ảnh rỗng, nhiễu, timing)
└── README.md
```

---

## 3. Hướng dẫn chạy kiểm thử (Unit Tests)

Kích hoạt môi trường ảo `venv` và chạy:
```bash
$env:PYTHONPATH = "d:\CDIO4"
.\venv\Scripts\python.exe -m pytest ai/tests -v
```
Toàn bộ test phải pass 100% không gặp lỗi crash.

