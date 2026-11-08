import base64
from datetime import datetime, timezone
from io import BytesIO
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from starlette.websockets import WebSocketDisconnect

from app.main import app


def jpeg_base64() -> str:
    stream = BytesIO()
    Image.new("RGB", (32, 24), "gray").save(stream, format="JPEG")
    return base64.b64encode(stream.getvalue()).decode("ascii")


def make_session(client: TestClient) -> str:
    response = client.post("/api/v1/sessions")
    assert response.status_code == 201
    return response.json()["session_id"]


def frame(session_id: str, frame_id: int = 1) -> dict:
    return {
        "type": "frame",
        "session_id": session_id,
        "frame_id": frame_id,
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "image_format": "jpeg",
        "image_base64": jpeg_base64(),
    }


def test_health_and_create_session():
    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
        assert "session_id" in client.post("/api/v1/sessions").json()


def test_valid_frame_returns_ai_analysis():
    with TestClient(app) as client:
        session_id = make_session(client)
        with client.websocket_connect(f"/ws/monitor?session_id={session_id}") as ws:
            ws.send_json(frame(session_id))
            result = ws.receive_json()
            assert result["type"] == "analysis_result"
            # Khung hình xám nhỏ không có mặt -> MONITORING_UNAVAILABLE
            assert result["state"] in ["MONITORING_UNAVAILABLE", "NOT_EVALUATED"]
            assert result["model_version"] == "baseline-mediapipe-v0.1"


def test_invalid_payload_does_not_crash_connection():
    with TestClient(app) as client:
        session_id = make_session(client)
        with client.websocket_connect(f"/ws/monitor?session_id={session_id}") as ws:
            ws.send_json({"type": "frame", "image_base64": "!!!"})
            assert ws.receive_json()["code"] == "INVALID_FRAME"


def test_unknown_session_is_rejected():
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(f"/ws/monitor?session_id={uuid4()}"):
                pass


def test_oversized_image_rejected():
    with TestClient(app) as client:
        session_id = make_session(client)
        payload = frame(session_id)
        payload["image_base64"] = base64.b64encode(b"x" * (2 * 1024 * 1024 + 1)).decode()
        with client.websocket_connect(f"/ws/monitor?session_id={session_id}") as ws:
            ws.send_json(payload)
            assert ws.receive_json()["code"] == "INVALID_FRAME"


def test_duplicate_frame_rejected():
    with TestClient(app) as client:
        session_id = make_session(client)
        with client.websocket_connect(f"/ws/monitor?session_id={session_id}") as ws:
            ws.send_json(frame(session_id, 4))
            assert ws.receive_json()["type"] == "analysis_result"
            ws.send_json(frame(session_id, 4))
            assert ws.receive_json()["code"] == "INVALID_FRAME"


def test_stale_frame_rejected():
    with TestClient(app) as client:
        session_id = make_session(client)
        payload = frame(session_id)
        payload["captured_at"] = "2020-01-01T00:00:00Z"
        with client.websocket_connect(f"/ws/monitor?session_id={session_id}") as ws:
            ws.send_json(payload)
            assert ws.receive_json()["code"] == "INVALID_FRAME"


def test_disconnect_releases_session_connection():
    with TestClient(app) as client:
        session_id = make_session(client)
        with client.websocket_connect(f"/ws/monitor?session_id={session_id}"):
            pass
        with client.websocket_connect(f"/ws/monitor?session_id={session_id}"):
            pass
