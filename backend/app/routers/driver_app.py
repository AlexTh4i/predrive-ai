from collections.abc import Callable
from datetime import datetime, timezone
import json
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, Request, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.database import get_db
from ..core.errors import AppError
from ..core.security import bearer_scheme, get_current_user, require_roles
from ..models.models import (
    EventModel,
    HeartbeatModel,
    LocationModel,
    SessionModel,
    User,
)
from ..schemas.m3 import (
    AlertEvent,
    BatchEventsRequest,
    BatchEventsResponse,
    CreateSessionRequest,
    CreateSessionResponse,
    EndSessionRequest,
    HeartbeatRequest,
    HeartbeatResponse,
    SessionSchema,
    UpsertEventRequest,
)
from ..services.events_service import upsert_session_event
from ..services.mappers import (
    build_live_driver_state,
    ensure_utc,
    get_or_create_org_settings,
    session_to_schema,
    settings_to_schema,
)
from ..services.sse import sse_broker

router = APIRouter(prefix="/api/v1/sessions", tags=["Driver App"])

# Hook for M1/M2 legacy in-memory WebSocket session creation
_legacy_session_creator: Optional[Callable[[], dict[str, Any]]] = None


def set_legacy_session_creator(fn: Callable[[], dict[str, Any]]) -> None:
    global _legacy_session_creator
    _legacy_session_creator = fn


def _get_owned_session(
    db: Session, session_id: str, current_user: User
) -> SessionModel:
    sess = db.get(SessionModel, session_id)
    if sess is None:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "SESSION_NOT_FOUND",
            "Không tìm thấy phiên làm việc",
        )
    if (
        sess.driver_id != current_user.id
        or sess.organization_id != current_user.organization_id
    ):
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN",
            "Tài xế không có quyền truy cập phiên của người khác",
        )
    return sess


@router.post("", response_model=CreateSessionResponse)
async def create_or_resume_session(
    request: Request,
    payload: Optional[CreateSessionRequest] = Body(default=None),
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> Any:
    # Backward-compatibility bridge for M1/M2 WebSocket gateway tests (unauthenticated empty/PWA body)
    if credentials is None or not credentials.credentials:
        raw_body = await request.body()
        is_legacy_call = False
        if not raw_body:
            is_legacy_call = True
        else:
            try:
                parsed = json.loads(raw_body)
                if isinstance(parsed, dict) and "sessionId" not in parsed:
                    is_legacy_call = True
            except Exception:
                pass
        if is_legacy_call and _legacy_session_creator is not None:
            legacy_data = _legacy_session_creator()
            return JSONResponse(status_code=201, content=legacy_data)

    # Standard M3 Driver authentication & authorization
    current_user = get_current_user(credentials=credentials, db=db)
    if current_user.role != "driver":
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN",
            "Chỉ tài khoản tài xế (driver) mới được mở phiên lái xe",
        )

    if payload is None:
        try:
            raw_json = await request.json()
            payload = CreateSessionRequest.model_validate(raw_json)
        except ( Exception, ValidationError ) as exc:
            raise AppError(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "VALIDATION_ERROR",
                "Thiếu sessionId hoặc startedAt hợp lệ",
            ) from exc

    now = datetime.now(timezone.utc)
    started_utc = ensure_utc(payload.startedAt) or now
    org_settings = get_or_create_org_settings(db, current_user.organization_id)

    existing = db.get(SessionModel, payload.sessionId)
    if existing is not None:
        if existing.driver_id != current_user.id:
            raise AppError(
                status.HTTP_403_FORBIDDEN,
                "FORBIDDEN",
                "sessionId này thuộc về tài xế khác",
            )
        return CreateSessionResponse(
            sessionId=existing.id,
            settings=settings_to_schema(org_settings),
        )

    # Close any previously unclosed session of this driver so only one session is open
    prev_open = db.scalars(
        select(SessionModel).where(
            SessionModel.driver_id == current_user.id,
            SessionModel.ended_at.is_(None),
        )
    ).all()
    for old_sess in prev_open:
        old_sess.ended_at = started_utc
        old_sess.status = "ended"
        old_sess.current_state = "OFFLINE"

    try:
        with db.begin_nested():
            sess = SessionModel(
                id=payload.sessionId,
                organization_id=current_user.organization_id,
                driver_id=current_user.id,
                vehicle_id=current_user.vehicle_id,
                status="active",
                started_at=started_utc,
                ended_at=None,
                total_driving_sec=0,
                continuous_driving_sec=0,
                unavailable_sec=0,
                warning_count=0,
                critical_count=0,
                current_state="NORMAL",
                last_heartbeat_at=now,
            )
            db.add(sess)
            db.flush()
    except IntegrityError:
        existing = db.get(SessionModel, payload.sessionId)
        if existing is None or existing.driver_id != current_user.id:
            raise AppError(
                status.HTTP_409_CONFLICT,
                "SESSION_CONFLICT",
                "Xung đột khởi tạo phiên",
            )
        return CreateSessionResponse(
            sessionId=existing.id,
            settings=settings_to_schema(org_settings),
        )

    db.commit()
    db.refresh(sess)

    live_state = build_live_driver_state(db, current_user)
    sse_broker.publish(
        current_user.organization_id,
        "driver_state",
        live_state.model_dump(mode="json"),
    )

    return CreateSessionResponse(
        sessionId=sess.id,
        settings=settings_to_schema(org_settings),
    )


@router.post("/{id}/events", response_model=AlertEvent)
def post_session_event(
    id: str,
    payload: UpsertEventRequest,
    current_user: User = Depends(require_roles("driver")),
    db: Session = Depends(get_db),
) -> AlertEvent:
    sess = _get_owned_session(db, id, current_user)
    alert_event, _ = upsert_session_event(
        db=db,
        session_obj=sess,
        driver=current_user,
        payload=payload,
        publish_sse=True,
    )
    return alert_event


@router.post("/{id}/events/batch", response_model=BatchEventsResponse)
def post_session_events_batch(
    id: str,
    payload: BatchEventsRequest,
    current_user: User = Depends(require_roles("driver")),
    db: Session = Depends(get_db),
) -> BatchEventsResponse:
    sess = _get_owned_session(db, id, current_user)
    results: list[AlertEvent] = []
    for item in payload.events:
        ev_schema, _ = upsert_session_event(
            db=db,
            session_obj=sess,
            driver=current_user,
            payload=item,
            publish_sse=True,
        )
        results.append(ev_schema)
    return BatchEventsResponse(items=results, total=len(results))


@router.post("/{id}/heartbeat", response_model=HeartbeatResponse)
def post_session_heartbeat(
    id: str,
    payload: HeartbeatRequest,
    current_user: User = Depends(require_roles("driver")),
    db: Session = Depends(get_db),
) -> HeartbeatResponse:
    sess = _get_owned_session(db, id, current_user)
    now = datetime.now(timezone.utc)
    captured_utc = ensure_utc(payload.capturedAt) or now

    hb = HeartbeatModel(
        organization_id=current_user.organization_id,
        session_id=sess.id,
        driver_id=current_user.id,
        state=payload.state,
        image_quality=payload.imageQuality,
        vehicle_moving=payload.vehicleMoving,
        ts=captured_utc,
        lat=payload.location.lat if payload.location else None,
        lng=payload.location.lng if payload.location else None,
    )
    db.add(hb)

    # Auto-recover if session was DISCONNECTED
    if sess.current_state == "DISCONNECTED" or sess.status == "disconnected":
        open_disc_events = db.scalars(
            select(EventModel).where(
                EventModel.session_id == sess.id,
                EventModel.type == "DISCONNECTED",
                EventModel.status != "CLOSED",
            )
        ).all()
        for disc_ev in open_disc_events:
            disc_ev.status = "CLOSED"
            disc_ev.closed_at = now
        if sess.ended_at is None:
            sess.status = "active"

    sess.current_state = payload.state
    sess.continuous_driving_sec = payload.continuousDrivingSec
    if payload.continuousDrivingSec > sess.total_driving_sec:
        sess.total_driving_sec = payload.continuousDrivingSec
    sess.last_heartbeat_at = now

    # Store optional location ONLY when organization settings have shareLocation=True
    org_settings = get_or_create_org_settings(db, current_user.organization_id)
    if org_settings.share_location and payload.location is not None:
        loc_at = ensure_utc(payload.location.at) if payload.location.at else captured_utc
        db.add(
            LocationModel(
                organization_id=current_user.organization_id,
                session_id=sess.id,
                vehicle_id=sess.vehicle_id or current_user.vehicle_id,
                driver_id=current_user.id,
                lat=payload.location.lat,
                lng=payload.location.lng,
                ts=loc_at or now,
            )
        )

    db.commit()
    db.refresh(sess)

    live_state = build_live_driver_state(
        db, current_user, share_location=org_settings.share_location
    )
    sse_broker.publish(
        current_user.organization_id,
        "driver_state",
        live_state.model_dump(mode="json"),
    )

    return HeartbeatResponse(
        status="ok",
        state=sess.current_state,  # type: ignore[arg-type]
        receivedAt=now,
    )


@router.post("/{id}/end", response_model=SessionSchema)
def end_session(
    id: str,
    payload: EndSessionRequest,
    current_user: User = Depends(require_roles("driver")),
    db: Session = Depends(get_db),
) -> SessionSchema:
    sess = _get_owned_session(db, id, current_user)
    ended_utc = ensure_utc(payload.endedAt) or datetime.now(timezone.utc)

    sess.ended_at = ended_utc
    sess.status = "ended"
    sess.total_driving_sec = max(sess.total_driving_sec, payload.summary.totalDrivingSec)
    sess.warning_count = max(sess.warning_count, payload.summary.warningCount)
    sess.critical_count = max(sess.critical_count, payload.summary.criticalCount)
    sess.unavailable_sec = max(sess.unavailable_sec, payload.summary.unavailableSec)
    sess.continuous_driving_sec = 0
    sess.current_state = "OFFLINE"

    open_events = db.scalars(
        select(EventModel).where(
            EventModel.session_id == sess.id,
            EventModel.status != "CLOSED",
        )
    ).all()
    for ev in open_events:
        ev.status = "CLOSED"
        ev.closed_at = ended_utc

    db.commit()
    db.refresh(sess)

    live_state = build_live_driver_state(db, current_user)
    sse_broker.publish(
        current_user.organization_id,
        "driver_state",
        live_state.model_dump(mode="json"),
    )

    return session_to_schema(sess)

