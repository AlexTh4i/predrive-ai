import os
import time
from typing import Dict, Optional, Tuple
import cv2
import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import numpy as np
from scipy.spatial import distance as dist

from ai.inference.quality import assess_image_quality
from ai.schemas import AIAnalysisOutput, DriverState, AlertLevel


class SessionMonitorState:
    """Quản lý trạng thái chuỗi thời gian cho từng phiên (session)."""
    def __init__(self):
        self.eye_closed_start_time: Optional[float] = None
        self.distracted_start_time: Optional[float] = None
        self.last_seen_time: float = time.monotonic()


class DriverMonitorAI:
    def __init__(
        self,
        model_path: Optional[str] = None,
        ear_threshold: float = 0.28,
        drowsy_warning_limit: float = 1.0,
        drowsy_critical_limit: float = 2.0,
        distracted_limit: float = 1.8,
    ):
        if model_path is None:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            model_path = os.path.join(base_dir, "models", "face_landmarker.task")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Không tìm thấy file model: {model_path}")

        base_options = python.BaseOptions(model_asset_path=model_path)
        options = vision.FaceLandmarkerOptions(base_options=base_options, num_faces=1)
        self.face_landmarker = vision.FaceLandmarker.create_from_options(options)

        # Cấu hình ngưỡng
        self.ear_threshold = ear_threshold
        self.drowsy_warning_limit = drowsy_warning_limit
        self.drowsy_critical_limit = drowsy_critical_limit
        self.distracted_limit = distracted_limit

        # Landmark mắt chuẩn (từ đồ án gốc của tác giả)
        self.LEFT_EYE = [33, 160, 158, 133, 153, 144]
        self.RIGHT_EYE = [362, 385, 387, 263, 373, 380]

        # Quản lý trạng thái đa phiên
        self._sessions: Dict[str, SessionMonitorState] = {}

    def _get_session(self, session_id: str) -> SessionMonitorState:
        now = time.monotonic()
        # Dọn dẹp session không hoạt động > 1 tiếng
        expired = [sid for sid, s in self._sessions.items() if now - s.last_seen_time > 3600]
        for sid in expired:
            self._sessions.pop(sid, None)

        if session_id not in self._sessions:
            self._sessions[session_id] = SessionMonitorState()
        session = self._sessions[session_id]
        session.last_seen_time = now
        return session

    def calculate_ear(self, landmarks, eye_indices, img_w: int, img_h: int) -> float:
        pts = []
        for idx in eye_indices:
            lm = landmarks[idx]
            pts.append((lm.x * img_w, lm.y * img_h))
        pts = np.array(pts)
        v1 = dist.euclidean(pts[1], pts[5])
        v2 = dist.euclidean(pts[2], pts[4])
        h1 = dist.euclidean(pts[0], pts[3])
        if h1 < 1e-6:
            return 0.0
        return float((v1 + v2) / (2.0 * h1))

    def check_head_pose(self, landmarks) -> bool:
        """Kiểm tra xem đầu có hướng về phía trước hay không (True = bình thường, False = mất tập trung)."""
        nose = landmarks[1]
        # Nếu mũi lệch quá nhiều sang trái/phải hoặc gục đầu xuống quá thấp
        if nose.y > 0.72 or nose.x < 0.30 or nose.x > 0.70:
            return False
        return True

    def analyze(self, frame_bgr: np.ndarray, session_id: str) -> AIAnalysisOutput:
        start_time = time.perf_counter()
        session = self._get_session(session_id)
        now_mono = time.monotonic()

        # 1. Kiểm tra khung hình hợp lệ
        if frame_bgr is None or frame_bgr.size == 0:
            return AIAnalysisOutput(
                state="MONITORING_UNAVAILABLE",
                alert_level="NONE",
                face_visible=False,
                image_quality="UNKNOWN",
                risk_score=None,
                processing_ms=int((time.perf_counter() - start_time) * 1000),
            )

        # 2. Đánh giá chất lượng ảnh
        quality = assess_image_quality(frame_bgr)
        if quality == "TOO_DARK":
            session.eye_closed_start_time = None
            session.distracted_start_time = None
            return AIAnalysisOutput(
                state="MONITORING_UNAVAILABLE",
                alert_level="NONE",
                face_visible=False,
                image_quality="TOO_DARK",
                risk_score=None,
                processing_ms=int((time.perf_counter() - start_time) * 1000),
            )

        # 3. Chạy MediaPipe FaceLandmarker
        h, w = frame_bgr.shape[:2]
        rgb_frame = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

        try:
            results = self.face_landmarker.detect(mp_image)
        except Exception:
            return AIAnalysisOutput(
                state="MONITORING_UNAVAILABLE",
                alert_level="NONE",
                face_visible=False,
                image_quality=quality,
                risk_score=None,
                processing_ms=int((time.perf_counter() - start_time) * 1000),
            )

        # 4. Kiểm tra phát hiện khuôn mặt
        if not results.face_landmarks:
            session.eye_closed_start_time = None
            session.distracted_start_time = None
            return AIAnalysisOutput(
                state="MONITORING_UNAVAILABLE",
                alert_level="NONE",
                face_visible=False,
                image_quality=quality,
                risk_score=None,
                processing_ms=int((time.perf_counter() - start_time) * 1000),
            )

        landmarks = results.face_landmarks[0]

        # 5. Tính EAR cho 2 mắt
        ear_left = self.calculate_ear(landmarks, self.LEFT_EYE, w, h)
        ear_right = self.calculate_ear(landmarks, self.RIGHT_EYE, w, h)
        avg_ear = float((ear_left + ear_right) / 2.0)

        # 6. Kiểm tra hướng đầu (Head Pose)
        is_facing_front = self.check_head_pose(landmarks)
        is_distracted = not is_facing_front

        # 7. Cập nhật bộ đếm thời gian
        # Nhắm mắt
        if avg_ear < self.ear_threshold:
            if session.eye_closed_start_time is None:
                session.eye_closed_start_time = now_mono
        else:
            session.eye_closed_start_time = None

        # Mất tập trung (quay đầu, gục đầu)
        if is_distracted:
            if session.distracted_start_time is None:
                session.distracted_start_time = now_mono
        else:
            session.distracted_start_time = None

        # 8. Ra quyết định trạng thái & mức cảnh báo
        state: DriverState = "NORMAL"
        alert_level: AlertLevel = "NONE"
        risk_score: Optional[float] = 0.05

        eye_closed_duration = (
            now_mono - session.eye_closed_start_time if session.eye_closed_start_time else 0.0
        )
        distracted_duration = (
            now_mono - session.distracted_start_time if session.distracted_start_time else 0.0
        )

        if eye_closed_duration >= self.drowsy_critical_limit:
            state = "CRITICAL"
            alert_level = "CRITICAL"
            risk_score = 0.95
        elif eye_closed_duration >= self.drowsy_warning_limit:
            state = "DROWSINESS_SIGNS"
            alert_level = "WARNING"
            risk_score = 0.80
        elif distracted_duration >= self.distracted_limit:
            state = "DISTRACTED"
            alert_level = "WARNING"
            risk_score = 0.65
        else:
            state = "NORMAL"
            alert_level = "NONE"
            risk_score = 0.10

        elapsed_ms = int((time.perf_counter() - start_time) * 1000)

        return AIAnalysisOutput(
            state=state,
            alert_level=alert_level,
            face_visible=True,
            image_quality=quality,
            risk_score=risk_score,
            ear=round(avg_ear, 3),
            is_distracted=is_distracted,
            processing_ms=elapsed_ms,
        )

