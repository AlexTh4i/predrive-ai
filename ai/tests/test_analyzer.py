import numpy as np
import pytest
from ai.inference.analyzer import DriverMonitorAI
from ai.inference.quality import assess_image_quality


@pytest.fixture(scope="module")
def ai_engine():
    return DriverMonitorAI()


def test_empty_or_none_frame(ai_engine):
    """Kiểm tra frame rỗng không làm crash hệ thống."""
    res = ai_engine.analyze(None, "test-session-1")
    assert res.state == "MONITORING_UNAVAILABLE"
    assert res.face_visible is False

    empty_arr = np.array([])
    res_empty = ai_engine.analyze(empty_arr, "test-session-1")
    assert res_empty.state == "MONITORING_UNAVAILABLE"
    assert res_empty.face_visible is False


def test_black_or_too_dark_frame(ai_engine):
    """Kiểm tra ảnh đen xì / thiếu sáng trầm trọng."""
    black_img = np.zeros((480, 640, 3), dtype=np.uint8)
    assert assess_image_quality(black_img) == "TOO_DARK"

    res = ai_engine.analyze(black_img, "test-session-2")
    assert res.state == "MONITORING_UNAVAILABLE"
    assert res.image_quality == "TOO_DARK"
    assert res.alert_level == "NONE"
    assert res.face_visible is False


def test_random_noise_no_face(ai_engine):
    """Kiểm tra ảnh nhiễu ngẫu nhiên không có mặt."""
    noise_img = np.random.randint(50, 200, (480, 640, 3), dtype=np.uint8)
    res = ai_engine.analyze(noise_img, "test-session-3")
    assert res.state == "MONITORING_UNAVAILABLE"
    assert res.face_visible is False


def test_model_version_and_timing(ai_engine):
    """Kiểm tra version và thời gian xử lý."""
    blank_img = np.full((480, 640, 3), 120, dtype=np.uint8)
    res = ai_engine.analyze(blank_img, "test-session-4")
    assert res.model_version == "baseline-mediapipe-v0.1"
    assert res.processing_ms >= 0

