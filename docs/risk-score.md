# Công thức Tính Điểm Rủi Ro Tài xế (`risk_scores`) — PreDrive AI

Tài liệu này mô tả công thức chuẩn hóa điểm rủi ro an toàn (`0..100`, điểm càng cao rủi ro càng lớn) áp dụng cho từng tài xế theo **ca (`shift`)**, **tuần (`weekly`)** và **tháng (`monthly`)** trong bảng `risk_scores`.

## 1. Phạm vi dữ liệu đầu vào
Trong khoảng thời gian `[period_start, period_end]` (tính theo múi giờ vận hành `Asia/Ho_Chi_Minh`, lọc nghiêm ngặt theo `organization_id`):
- **Giờ lái (`driving_hours`):** tổng `sessions.total_driving_sec / 3600.0` làm tròn 1 chữ số thập phân.
- **Sự kiện hợp lệ:** tất cả bản ghi trong bảng `events` của tài xế trong kỳ, **ngoại trừ** các cảnh báo đã được tài xế xác nhận là báo sai (`driver_feedback = 'false_alarm'`).
  - `critical_events`: số sự kiện mức 3 (`level >= 3`).
  - `drowsy_non_critical`: số sự kiện buồn ngủ (`type IN ('DROWSINESS', 'DROWSY', 'HEAD_DOWN')` và `level < 3`).
  - `distraction_events`: số sự kiện mất tập trung (`type = 'DISTRACTED'`).
  - `overtime_events`: số sự kiện vi phạm giờ lái liên tục / nghỉ không đạt (`type IN ('LONG_DRIVING', 'REST_CLAIM_REJECTED')`).

## 2. Trọng số cấu hình được (Configurable Weights)
Mọi trọng số đều có thể điều chỉnh qua biến môi trường hoặc tham số API khi tính lại mà không cần sửa mã nguồn:

| Tham số | Biến môi trường | Mặc định | Ý nghĩa |
|---|---|---|---|
| `w_critical` | `RISK_WEIGHT_CRITICAL` | `25.0` | Điểm phạt mỗi sự kiện Nguy hiểm (Mức 3) |
| `w_drowsy` | `RISK_WEIGHT_DROWSY` | `12.0` | Điểm phạt mỗi sự kiện Buồn ngủ (Mức 1–2) |
| `w_distraction` | `RISK_WEIGHT_DISTRACTION` | `6.0` | Điểm phạt mỗi sự kiện Mất tập trung |
| `w_overtime` | `RISK_WEIGHT_OVERTIME` | `10.0` | Điểm phạt mỗi sự kiện Quá giờ lái / Nghỉ chưa đủ |
| `shift_hours_norm` | `RISK_SHIFT_HOURS_NORM` | `8.0` | Hệ số chuẩn hóa theo 1 ca lái tiêu chuẩn (8 giờ) |

## 3. Công thức toán học
1. **Tổng điểm phạt thô (`weighted_points`):**
   $$\text{weighted\_points} = w_{\text{critical}} \cdot N_{\text{critical}} + w_{\text{drowsy}} \cdot N_{\text{drowsy\_non\_crit}} + w_{\text{distraction}} \cdot N_{\text{distraction}} + w_{\text{overtime}} \cdot N_{\text{overtime}}$$

2. **Hệ số phơi nhiễm giờ lái (`exposure_factor`):**
   $$\text{exposure\_factor} = \max\left(1.0,\ \frac{\text{driving\_hours}}{\text{shift\_hours\_norm}}\right)$$
   *(Tài xế lái nhiều ca chuẩn 8 giờ được chuẩn hóa công bằng theo thời lượng vận hành thực tế).*

3. **Điểm rủi ro chuẩn hóa (`score` $\in [0, 100]$):**
   $$\text{score} = \min\left(100,\ \max\left(0,\ \text{round}\left(\frac{\text{weighted\_points}}{\text{exposure\_factor}}\right)\right)\right)$$

4. **Phân hạng mức rủi ro (`risk_level`):**
   - `low`: `0 <= score < 35`
   - `medium`: `35 <= score < 70`
   - `high`: `70 <= score <= 100`
