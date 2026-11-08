import asyncio
import base64
import binascii
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
from uuid import UUID, uuid4

import cv2
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
import numpy as np
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError

# Đảm bảo đường dẫn gốc chứa module ai/
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from ai import DriverMonitorAI
from .schemas import AnalysisResult, FrameMessage, SessionResponse

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("predrive.backend")


def setting(name: str, default: int) -> int:
    try:
        return max(1, int(os.getenv(name, str(default))))
    except ValueError:
        return default


MAX_FRAME_BYTES = setting("PREDRIVE_MAX_FRAME_BYTES", 2 * 1024 * 1024)
MAX_IMAGE_WIDTH = setting("PREDRIVE_MAX_IMAGE_WIDTH", 1920)
MAX_IMAGE_HEIGHT = setting("PREDRIVE_MAX_IMAGE_HEIGHT", 1080)
MAX_FPS = setting("PREDRIVE_MAX_FPS", 10)
MAX_CONNECTIONS = setting("PREDRIVE_MAX_CONNECTIONS", 20)
MAX_SESSIONS = setting("PREDRIVE_MAX_SESSIONS", 100)
MAX_FRAME_AGE = setting("PREDRIVE_MAX_FRAME_AGE_SECONDS", 60)
MAX_FUTURE_SKEW = setting("PREDRIVE_MAX_FUTURE_SKEW_SECONDS", 60)
SESSION_TTL = setting("PREDRIVE_SESSION_TTL_SECONDS", 3600)

sessions: dict[UUID, datetime] = {}
active_sessions: set[UUID] = set()

# Khởi tạo instance AI phân tích giám sát
ai_analyzer: DriverMonitorAI = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    global ai_analyzer
    logger.info("Đang khởi tạo AI Model...")
    ai_analyzer = DriverMonitorAI()
    logger.info("AI Model đã sẵn sàng!")
    yield
    sessions.clear()
    active_sessions.clear()


app = FastAPI(title="PREDRIVE AI Gateway", version="0.1.0", lifespan=lifespan)
origins = [o.strip() for o in os.getenv("PREDRIVE_ALLOWED_ORIGINS", "http://localhost:5173").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "predrive-backend", "version": "0.1.0"}


@app.post("/api/v1/sessions", response_model=SessionResponse, status_code=201)
async def create_session() -> SessionResponse:
    now = datetime.now(timezone.utc)
    if len(sessions) >= MAX_SESSIONS:
        expired = [sid for sid, expires in sessions.items() if expires <= now]
        for sid in expired:
            sessions.pop(sid, None)
        if len(sessions) >= MAX_SESSIONS:
            raise HTTPException(status_code=503, detail="session capacity reached")
    session_id = uuid4()
    expires_at = now + timedelta(seconds=SESSION_TTL)
    sessions[session_id] = expires_at
    return SessionResponse(session_id=session_id, created_at=now, expires_at=expires_at)


def decode_jpeg(encoded: str) -> tuple[bytes, tuple[int, int]]:
    # Reject pathological input before allocating the decoded buffer.
    if len(encoded) > ((MAX_FRAME_BYTES + 2) // 3) * 4 + 4:
        raise ValueError("image exceeds size limit")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("image_base64 is not valid base64") from exc
    if not raw or len(raw) > MAX_FRAME_BYTES:
        raise ValueError("image exceeds size limit or is empty")
    try:
        with Image.open(BytesIO(raw)) as image:
            if image.format != "JPEG":
                raise ValueError("image content must be JPEG")
            width, height = image.size
            if width > MAX_IMAGE_WIDTH or height > MAX_IMAGE_HEIGHT:
                raise ValueError("image dimensions exceed limit")
            image.verify()
        return raw, (width, height)
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("image content is not a valid JPEG") from exc


def parse_frame(payload: str) -> FrameMessage:
    if len(payload.encode("utf-8")) > MAX_FRAME_BYTES * 2:
        raise ValueError("message exceeds size limit")
    try:
        return FrameMessage.model_validate_json(payload)
    except ValidationError as exc:
        raise ValueError("invalid frame schema") from exc


@app.websocket("/ws/monitor")
async def monitor(websocket: WebSocket, session_id: str) -> None:
    try:
        parsed_session = UUID(session_id)
    except ValueError:
        await websocket.close(code=1008, reason="invalid session_id")
        return
    expires_at = sessions.get(parsed_session)
    if expires_at is None or expires_at <= datetime.now(timezone.utc):
        sessions.pop(parsed_session, None)
        await websocket.close(code=1008, reason="unknown or expired session")
        return
    if parsed_session in active_sessions:
        await websocket.close(code=1013, reason="session already connected")
        return
    if len(active_sessions) >= MAX_CONNECTIONS:
        await websocket.close(code=1013, reason="connection capacity reached")
        return

    await websocket.accept()
    active_sessions.add(parsed_session)
    last_frame_id = -1
    frame_times: list[float] = []
    last_seen = time.monotonic()
    try:
        while True:
            try:
                message = await asyncio.wait_for(websocket.receive_text(), timeout=60)
            except asyncio.TimeoutError:
                await websocket.close(code=1001, reason="heartbeat timeout")
                break
            now_mono = time.monotonic()
            if now_mono - last_seen > 60:
                await websocket.close(code=1001, reason="heartbeat timeout")
                break
            last_seen = now_mono
            try:
                frame = parse_frame(message)
                if frame.session_id != parsed_session:
                    raise ValueError("session_id does not match connection")
                if frame.frame_id <= last_frame_id:
                    raise ValueError("frame_id must increase")
                now = datetime.now(timezone.utc)
                age = (now - frame.captured_at).total_seconds()
                if age > MAX_FRAME_AGE:
                    raise ValueError("stale frame")
                if age < -MAX_FUTURE_SKEW:
                    raise ValueError("captured_at is too far in the future")
                raw_bytes, (width, height) = decode_jpeg(frame.image_base64)
                frame_times = [t for t in frame_times if now_mono - t < 1]
                if len(frame_times) >= MAX_FPS:
                    raise ValueError("frame rate limit exceeded")
                frame_times.append(now_mono)
            except ValueError as exc:
                print(f"[BACKEND WARNING] Frame rejected: {exc}", flush=True)
                await websocket.send_json({"type": "error", "code": "INVALID_FRAME", "detail": str(exc)})
                continue

            last_frame_id = frame.frame_id
            processed_at = datetime.now(timezone.utc)

            # Phân tích AI từ frame ảnh
            if ai_analyzer is not None:
                nparr = np.frombuffer(raw_bytes, np.uint8)
                frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                ai_output = ai_analyzer.analyze(frame_bgr, session_id=str(parsed_session))
                print(f"[AI] Frame {frame.frame_id} | State: {ai_output.state} | Alert: {ai_output.alert_level} | EAR: {ai_output.ear} | Quality: {ai_output.image_quality}", flush=True)
                response = AnalysisResult(
                    session_id=parsed_session,
                    frame_id=frame.frame_id,
                    captured_at=frame.captured_at,
                    processed_at=processed_at,
                    model_version=ai_output.model_version,
                    state=ai_output.state,
                    alert_level=ai_output.alert_level,
                    face_visible=ai_output.face_visible,
                    image_quality=ai_output.image_quality,
                    risk_score=ai_output.risk_score,
                    processing_ms=ai_output.processing_ms,
                )
            else:
                response = AnalysisResult(
                    session_id=parsed_session,
                    frame_id=frame.frame_id,
                    captured_at=frame.captured_at,
                    processed_at=processed_at,
                    processing_ms=0,
                )

            await websocket.send_json(response.model_dump(mode="json"))
    except WebSocketDisconnect:
        pass
    finally:
        active_sessions.discard(parsed_session)
        logger.info("monitor session disconnected session_id=%s", parsed_session)
