import cv2
import numpy as np
from ai.schemas import ImageQuality


def assess_image_quality(frame: np.ndarray) -> ImageQuality:
    """Đánh giá chất lượng khung hình: độ sáng và độ mờ.
    - TOO_DARK: ảnh quá tối, không thể trích xuất đặc trưng tin cậy.
    - LOW_LIGHT: ảnh thiếu sáng nhưng vẫn có thể nhìn thấy đường nét.
    - BLURRY: ảnh bị rung/mờ (Laplacian variance thấp).
    - GOOD: ảnh rõ nét, ánh sáng đạt chuẩn.
    """
    if frame is None or frame.size == 0:
        return "UNKNOWN"

    # Chuyển ảnh xám
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY) if len(frame.shape) == 3 else frame

    # 1. Đo độ sáng trung bình (mean luminance)
    mean_brightness = float(np.mean(gray))
    if mean_brightness < 20.0:
        return "TOO_DARK"

    # 2. Đo độ sắc nét bằng phương sai Laplacian
    laplacian_var = float(cv2.Laplacian(gray, cv2.CV_64F).var())
    if laplacian_var < 35.0:
        return "BLURRY"

    if mean_brightness < 45.0:
        return "LOW_LIGHT"

    return "GOOD"

