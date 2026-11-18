import asyncio
import base64
import binascii
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from io import BytesIO
import logging
import os
import sys
import time
from typing import Any
from uuid import UUID, uuid4

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse
from PIL import Image, UnidentifiedImageError
from pydantic import ValidationError
from sqlalchemy import select

# Đảm bảo đường dẫn gốc chứa module ai/
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

try:
    import cv2
    import numpy as np
    from ai import DriverMonitorAI

    _LEGACY_AI_AVAILABLE = True
    _LEGACY_AI_IMPORT_ERROR: str | None = None
except ImportError as exc:
    cv2 = None  # type: ignore[assignment]
    np = None  # type: ignore[assignment]
    DriverMonitorAI = Any  # type: ignore[assignment,misc]
    _LEGACY_AI_AVAILABLE = False
    _LEGACY_AI_IMPORT_ERROR = str(exc)
from .core import database as db_mod
from .core.config import get_config
from .core.errors import register_error_handlers
from .models.models import Organization
from .routers import auth as auth_router
from .routers import driver_app as driver_app_router
from .routers import web_admin as web_admin_router
from .schemas import AnalysisResult, FrameMessage, SessionResponse
from .services.observability import (
    init_sentry_if_configured,
    record_http_metric,
    render_prometheus_metrics,
)
from .services.rate_limiter import rate_limiter
from .services.seed import seed_database
from .services.watchdog import watchdog_loop

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

# Khởi tạo instance AI phân tích giám sát (dùng cho legacy WebSocket M1/M2)
ai_analyzer: DriverMonitorAI | None = None


def _create_legacy_ws_session() -> dict[str, Any]:
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
    resp = SessionResponse(session_id=session_id, created_at=now, expires_at=expires_at)
    return resp.model_dump(mode="json")


driver_app_router.set_legacy_session_creator(_create_legacy_ws_session)


@asynccontextmanager
async def lifespan(_: FastAPI):
    global ai_analyzer
    # 1. Initialize database schema & seed if empty (NEVER seed in production - R5 / P0-4)
    rate_limiter.reset()
    init_sentry_if_configured()
    cfg = get_config()
    db_mod.Base.metadata.create_all(bind=db_mod.engine)
    if not cfg.is_production and os.getenv("PREDRIVE_AUTO_SEED", "1") == "1":
        with db_mod.SessionLocal() as db:
            has_org = db.scalar(select(Organization.id).limit(1))
            if has_org is None:
                logger.info("Database trống — đang chạy seed dữ liệu mẫu dev...")
                seed_database(db)
                logger.info("Đã hoàn tất seed dữ liệu mẫu dev.")

    # 2. Initialize AI Model for M1/M2 WebSocket gateway (optional in M3-only mode)
    enable_legacy_ai = os.getenv("PREDRIVE_ENABLE_LEGACY_AI", "1") == "1"
    if enable_legacy_ai and _LEGACY_AI_AVAILABLE:
        logger.info("Đang khởi tạo AI Model...")
        ai_analyzer = DriverMonitorAI()
        logger.info("AI Model đã sẵn sàng!")
    else:
        ai_analyzer = None
        if not enable_legacy_ai:
            logger.info("Chạy ở chế độ M3-only (PREDRIVE_ENABLE_LEGACY_AI=0).")
        else:
            logger.warning(
                "Thiếu dependency module ai/ (%s) — chạy backend ở chế độ M3-only.",
                _LEGACY_AI_IMPORT_ERROR,
            )

    # 3. Start background watchdog task for M3 session heartbeat monitoring
    stop_event = asyncio.Event()
    watchdog_task: asyncio.Task[None] | None = None
    if get_config().enable_watchdog:
        watchdog_task = asyncio.create_task(watchdog_loop(stop_event))

    try:
        yield
    finally:
        stop_event.set()
        if watchdog_task is not None:
            watchdog_task.cancel()
            try:
                await watchdog_task
            except asyncio.CancelledError:
                pass
        sessions.clear()
        active_sessions.clear()


_boot_cfg = get_config()
app = FastAPI(
    title="PREDRIVE AI Gateway & Fleet Backend",
    version="0.4.0",
    lifespan=lifespan,
    docs_url=None if _boot_cfg.is_production else "/docs",
    redoc_url=None if _boot_cfg.is_production else "/redoc",
    openapi_url=None if _boot_cfg.is_production else "/openapi.json",
)

register_error_handlers(app)

_DOCS_PATHS = {"/docs", "/docs/oauth2-redirect", "/redoc", "/openapi.json"}


def _apply_security_and_cors_headers(
    response: Response, origin: str | None, allowed_origins: list[str], is_prod: bool
) -> Response:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault(
        "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
    )
    if is_prod:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
        response.headers.setdefault(
            "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
        )
    if origin and origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers["Vary"] = "Origin"
    return response


@app.middleware("http")
async def production_security_middleware(request: Request, call_next):
    cfg = get_config()
    origin = request.headers.get("origin")

    # 1. Disable public Swagger / OpenAPI docs in production (R5 / P1-6)
    if cfg.is_production and request.url.path in _DOCS_PATHS:
        resp = JSONResponse(
            status_code=404,
            content={"error": {"code": "NOT_FOUND", "message": "Not Found"}},
        )
        return _apply_security_and_cors_headers(
            resp, origin, cfg.cors_origins, cfg.is_production
        )

    # 2. Dynamic CORS preflight strictly bound to CORS_ORIGINS
    if request.method == "OPTIONS" and "access-control-request-method" in request.headers:
        if origin and origin in cfg.cors_origins:
            preflight = PlainTextResponse("OK", status_code=200)
            preflight.headers["Access-Control-Allow-Methods"] = (
                "GET, POST, PUT, PATCH, DELETE, OPTIONS"
            )
            preflight.headers["Access-Control-Allow-Headers"] = (
                "Content-Type, Authorization, X-API-Key"
            )
            preflight.headers["Access-Control-Max-Age"] = "600"
            return _apply_security_and_cors_headers(
                preflight, origin, cfg.cors_origins, cfg.is_production
            )
        disallowed = PlainTextResponse("Disallowed CORS origin", status_code=400)
        return _apply_security_and_cors_headers(
            disallowed, None, cfg.cors_origins, cfg.is_production
        )

    # 3. Request body size limit (P1-6)
    max_bytes = cfg.max_body_bytes
    cl_header = request.headers.get("content-length")
    if cl_header:
        try:
            if int(cl_header) > max_bytes:
                too_large = JSONResponse(
                    status_code=413,
                    content={
                        "error": {
                            "code": "PAYLOAD_TOO_LARGE",
                            "message": f"Request body exceeds limit ({max_bytes} bytes)",
                        }
                    },
                )
                return _apply_security_and_cors_headers(
                    too_large, origin, cfg.cors_origins, cfg.is_production
                )
        except ValueError:
            pass

    if request.method in ("POST", "PUT", "PATCH"):
        body_bytes = await request.body()
        if len(body_bytes) > max_bytes:
            too_large = JSONResponse(
                status_code=413,
                content={
                    "error": {
                        "code": "PAYLOAD_TOO_LARGE",
                        "message": f"Request body exceeds limit ({max_bytes} bytes)",
                    }
                },
            )
            return _apply_security_and_cors_headers(
                too_large, origin, cfg.cors_origins, cfg.is_production
            )

    t_start = time.perf_counter()
    response = await call_next(request)
    elapsed = time.perf_counter() - t_start
    route_obj = request.scope.get("route")
    route_label = getattr(route_obj, "path", request.url.path)
    record_http_metric(request.method, route_label, response.status_code, elapsed)
    return _apply_security_and_cors_headers(
        response, origin, cfg.cors_origins, cfg.is_production
    )

# Mount M3 API routers
app.include_router(auth_router.router)
app.include_router(driver_app_router.router)
app.include_router(web_admin_router.router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "predrive-backend", "version": "0.1.0"}


@app.get("/metrics", include_in_schema=False)
async def metrics() -> Response:
    payload, content_type = render_prometheus_metrics()
    return Response(content=payload, media_type=content_type)


def decode_jpeg(encoded: str) -> tuple[bytes, tuple[int, int]]:
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
                await websocket.send_json(
                    {"type": "error", "code": "INVALID_FRAME", "detail": str(exc)}
                )
                continue

            last_frame_id = frame.frame_id
            processed_at = datetime.now(timezone.utc)

            if ai_analyzer is not None and cv2 is not None and np is not None:
                nparr = np.frombuffer(raw_bytes, np.uint8)
                frame_bgr = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                ai_output = ai_analyzer.analyze(frame_bgr, session_id=str(parsed_session))
                print(
                    f"[AI] Frame {frame.frame_id} | State: {ai_output.state} | Alert: {ai_output.alert_level} | EAR: {ai_output.ear} | Quality: {ai_output.image_quality}",
                    flush=True,
                )
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
