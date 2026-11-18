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
from ..core.security import bearer_scheme, get_current_user, get_jwt_org_id, require_roles
from uuid import uuid4
from ..models.models import (
    Consent,
    EventModel,
    HeartbeatModel,
    LocationModel,
    RestBreak,
    RestStop,
    SessionModel,
    User,
    Vehicle,
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
    LocationIngestRequest,
    LocationIngestResponse,
    LocationInputPoint,
    RestBreakEndRequest,
    RestBreakItem,
    RestBreakStartRequest,
    SessionSchema,
    SettingsSchema,
    UpsertEventRequest,
)
from ..services.events_service import _resolve_event_uuid, upsert_session_event
from ..services.mappers import (
    build_live_driver_state,
    ensure_utc,
    event_to_schema,
    get_or_create_org_settings,
    session_to_schema,
    settings_to_schema,
)
from ..services.observability import HEARTBEATS_RECEIVED_TOTAL
from ..services.rest_service import (
    compute_effective_continuous_sec,
    evaluate_driving_hours_and_rest_reminder,
    find_nearest_rest_stops,
)
from ..services.sse import sse_broker
from ..services.rate_limiter import enforce_events_rate_limit, enforce_heartbeat_rate_limit

router = APIRouter(prefix="/api/v1/sessions", tags=["Driver App"])

# Hook for M1/M2 legacy in-memory WebSocket session creation
_legacy_session_creator: Optional[Callable[[], dict[str, Any]]] = None


def set_legacy_session_creator(fn: Callable[[], dict[str, Any]]) -> None:
    global _legacy_session_creator
    _legacy_session_creator = fn


def _require_driver_consent(db: Session, current_user: User) -> Consent:
    org_id = get_jwt_org_id(current_user)
    consent = db.scalar(
        select(Consent)
        .where(
            Consent.user_id == current_user.id,
            Consent.organization_id == org_id,
            Consent.consent_type == "data_processing",
        )
        .order_by(Consent.accepted_at.desc())
    )
    if consent is None:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "CONSENT_REQUIRED",
            "Tài xế chưa xác nhận đồng ý xử lý dữ liệu theo Nghị định 13/2023/NĐ-CP",
        )
    return consent


def _get_owned_session(
    db: Session, session_id: str, current_user: User
) -> SessionModel:
    org_id = get_jwt_org_id(current_user)
    sess = db.get(SessionModel, session_id)
    if sess is None or sess.organization_id != org_id:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "SESSION_NOT_FOUND",
            "Không tìm thấy phiên làm việc",
        )
    if sess.driver_id != current_user.id:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            "FORBIDDEN",
            "Tài xế không có quyền truy cập phiên của người khác",
        )
    return sess


@router.get("/config", response_model=SettingsSchema)
def get_driver_runtime_config(
    current_user: User = Depends(require_roles("driver")),
    db: Session = Depends(get_db),
) -> SettingsSchema:
    org_id = get_jwt_org_id(current_user)
    org_settings = get_or_create_org_settings(db, org_id)
    return settings_to_schema(org_settings)


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
    org_id = get_jwt_org_id(current_user)
    org_settings = get_or_create_org_settings(db, org_id)

    existing = db.get(SessionModel, payload.sessionId)
    if existing is not None:
        if existing.organization_id != org_id or existing.driver_id != current_user.id:
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
    _require_driver_consent(db, current_user)
    sess = _get_owned_session(db, id, current_user)
    enforce_events_rate_limit(sess.id)
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
    _require_driver_consent(db, current_user)
    sess = _get_owned_session(db, id, current_user)
    enforce_events_rate_limit(sess.id)
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
    consent = _require_driver_consent(db, current_user)
    sess = _get_owned_session(db, id, current_user)
    enforce_heartbeat_rate_limit(sess.id)
    now = datetime.now(timezone.utc)
    captured_utc = ensure_utc(payload.capturedAt) or now

    org_settings = get_or_create_org_settings(db, get_jwt_org_id(current_user))
    allow_loc = bool(org_settings.share_location and consent.location_consent)

    hb = HeartbeatModel(
        organization_id=current_user.organization_id,
        session_id=sess.id,
        driver_id=current_user.id,
        state=payload.state,
        image_quality=payload.imageQuality,
        vehicle_moving=payload.vehicleMoving,
        ts=captured_utc,
        lat=payload.location.lat if (allow_loc and payload.location) else None,
        lng=payload.location.lng if (allow_loc and payload.location) else None,
        speed_kmh=payload.location.speedKmh if (allow_loc and payload.location) else None,
    )
    db.add(hb)
    HEARTBEATS_RECEIVED_TOTAL.inc()

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
    eff_cont_sec, last_rest_end = compute_effective_continuous_sec(
        db, sess, org_settings, payload.continuousDrivingSec, captured_utc
    )
    sess.continuous_driving_sec = eff_cont_sec
    if payload.continuousDrivingSec > sess.total_driving_sec:
        sess.total_driving_sec = payload.continuousDrivingSec
    sess.last_heartbeat_at = now

    # Store optional location ONLY when BOTH org settings AND driver consent allow location
    loc_lat = payload.location.lat if (allow_loc and payload.location) else None
    loc_lng = payload.location.lng if (allow_loc and payload.location) else None
    if allow_loc and payload.location is not None:
        loc_at = ensure_utc(payload.location.at) if payload.location.at else captured_utc
        db.add(
            LocationModel(
                organization_id=current_user.organization_id,
                session_id=sess.id,
                vehicle_id=sess.vehicle_id or current_user.vehicle_id,
                driver_id=current_user.id,
                lat=payload.location.lat,
                lng=payload.location.lng,
                speed_kmh=payload.location.speedKmh,
                heading_deg=payload.location.headingDeg,
                ts=loc_at or now,
            )
        )

    rest_reminder = evaluate_driving_hours_and_rest_reminder(
        db=db,
        sess=sess,
        driver=current_user,
        org_settings=org_settings,
        continuous_sec=eff_cont_sec,
        last_rest_end=last_rest_end,
        lat=loc_lat,
        lng=loc_lng,
        now_utc=captured_utc,
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
        settings=settings_to_schema(org_settings),
        restReminder=rest_reminder,
    )


@router.post("/{id}/rest-breaks/start", response_model=RestBreakItem, status_code=status.HTTP_201_CREATED)
def start_rest_break(
    id: str,
    payload: RestBreakStartRequest = Body(default=RestBreakStartRequest()),
    current_user: User = Depends(require_roles("driver")),
    db: Session = Depends(get_db),
) -> RestBreakItem:
    _require_driver_consent(db, current_user)
    sess = _get_owned_session(db, id, current_user)
    org_id = get_jwt_org_id(current_user)
    org_settings = get_or_create_org_settings(db, org_id)
    now = ensure_utc(payload.startedAt) or datetime.now(timezone.utc)

    active_rb = db.scalar(
        select(RestBreak)
        .where(
            RestBreak.organization_id == org_id,
            RestBreak.driver_id == current_user.id,
            RestBreak.session_id == sess.id,
            RestBreak.ended_at.is_(None),
        )
        .order_by(RestBreak.started_at.desc())
    )
    if active_rb is not None:
        return RestBreakItem(
            id=active_rb.id,
            sessionId=active_rb.session_id,
            driverId=active_rb.driver_id,
            driveMinBefore=active_rb.drive_min_before,
            suggestedStopId=active_rb.suggested_stop_id,
            startedAt=ensure_utc(active_rb.started_at),  # type: ignore[arg-type]
            endedAt=None,
        )

    eff_cont_sec, _ = compute_effective_continuous_sec(
        db, sess, org_settings, sess.continuous_driving_sec, now
    )
    drive_min_before = max(0, round(eff_cont_sec / 60))

    stop_id: Optional[str] = payload.suggestedStopId
    if stop_id:
        st = db.get(RestStop, stop_id)
        if st is None or (st.organization_id is not None and st.organization_id != org_id):
            stop_id = None
    elif payload.lat is not None and payload.lng is not None:
        nearest = find_nearest_rest_stops(db, org_id, payload.lat, payload.lng, limit=1)
        if nearest:
            stop_id = nearest[0].id

    rb = RestBreak(
        organization_id=org_id,
        driver_id=current_user.id,
        session_id=sess.id,
        drive_min_before=drive_min_before,
        reminder_sent_at=now,
        suggested_stop_id=stop_id,
        started_at=now,
        ended_at=None,
    )
    db.add(rb)
    db.commit()
    db.refresh(rb)

    return RestBreakItem(
        id=rb.id,
        sessionId=rb.session_id,
        driverId=rb.driver_id,
        driveMinBefore=rb.drive_min_before,
        suggestedStopId=rb.suggested_stop_id,
        startedAt=ensure_utc(rb.started_at),  # type: ignore[arg-type]
        endedAt=None,
    )


@router.post("/{id}/rest-breaks/end", response_model=RestBreakItem)
def end_rest_break(
    id: str,
    payload: RestBreakEndRequest = Body(default=RestBreakEndRequest()),
    current_user: User = Depends(require_roles("driver")),
    db: Session = Depends(get_db),
) -> RestBreakItem:
    _require_driver_consent(db, current_user)
    sess = _get_owned_session(db, id, current_user)
    org_id = get_jwt_org_id(current_user)
    org_settings = get_or_create_org_settings(db, org_id)
    now = ensure_utc(payload.endedAt) or datetime.now(timezone.utc)

    rb = db.scalar(
        select(RestBreak)
        .where(
            RestBreak.organization_id == org_id,
            RestBreak.driver_id == current_user.id,
            RestBreak.session_id == sess.id,
            RestBreak.ended_at.is_(None),
        )
        .order_by(RestBreak.started_at.desc())
    )
    if rb is None:
        raise AppError(
            status.HTTP_404_NOT_FOUND,
            "REST_BREAK_NOT_FOUND",
            "Không có kỳ nghỉ đang mở trong phiên này",
        )

    rb_start = ensure_utc(rb.started_at) or now
    rested_sec = max(0.0, (now - rb_start).total_seconds())
    rb.ended_at = now
    qualified = rested_sec >= float(org_settings.min_rest_min) * 60.0

    if sess.ended_at is None:
        sess.status = "active"

    if qualified:
        sess.continuous_driving_sec = 0
    else:
        ev_id = str(uuid4())
        ev = EventModel(
            id=ev_id,
            organization_id=org_id,
            session_id=sess.id,
            driver_id=current_user.id,
            vehicle_id=sess.vehicle_id or current_user.vehicle_id,
            client_event_id=f"rest-rej-{rb.id}",
            type="REST_CLAIM_REJECTED",
            level=2,
            status="OPEN",
            delayed=False,
            occurred_at=now,
            note=f"Nghỉ {round(rested_sec / 60.0, 1)} phút < tối thiểu {org_settings.min_rest_min} phút",
            created_at=now,
            metrics={
                "api_level": "WARNING",
                "alert_action": "notify_dispatcher",
                "state": sess.current_state,
                "duration_sec": int(rested_sec),
                "captured_at": now.isoformat(),
            },
        )
        db.add(ev)
        sess.warning_count += 1
        db.flush()

        v_name = "Chưa phân xe"
        v_id = sess.vehicle_id or current_user.vehicle_id
        if v_id:
            v_obj = db.get(Vehicle, v_id)
            if v_obj:
                v_name = v_obj.name
        sse_broker.publish(
            org_id,
            "alert",
            event_to_schema(ev, current_user.full_name, v_name).model_dump(mode="json"),
        )

    db.commit()
    db.refresh(rb)

    return RestBreakItem(
        id=rb.id,
        sessionId=rb.session_id,
        driverId=rb.driver_id,
        driveMinBefore=rb.drive_min_before,
        suggestedStopId=rb.suggested_stop_id,
        startedAt=rb_start,
        endedAt=now,
        restedMin=round(rested_sec / 60.0, 1),
        qualifiedReset=qualified,
    )


@router.post("/{id}/locations", response_model=LocationIngestResponse)
def post_session_locations(
    id: str,
    payload: LocationIngestRequest,
    current_user: User = Depends(require_roles("driver")),
    db: Session = Depends(get_db),
) -> LocationIngestResponse:
    consent = _require_driver_consent(db, current_user)
    sess = _get_owned_session(db, id, current_user)
    enforce_heartbeat_rate_limit(sess.id)

    org_id = get_jwt_org_id(current_user)
    org_settings = get_or_create_org_settings(db, org_id)
    allow_loc = bool(org_settings.share_location and consent.location_consent)
    if not allow_loc:
        return LocationIngestResponse(accepted=0, shareLocationEnabled=False)

    now = datetime.now(timezone.utc)
    items: list[LocationInputPoint] = list(payload.points)
    if payload.lat is not None and payload.lng is not None:
        items.append(
            LocationInputPoint(
                lat=payload.lat,
                lng=payload.lng,
                speedKmh=payload.speedKmh,
                headingDeg=payload.headingDeg,
                at=payload.at,
                eventId=payload.eventId,
            )
        )

    accepted = 0
    for pt in items:
        loc_ts = ensure_utc(pt.at) if pt.at else now
        linked_ev_id: Optional[str] = None
        if pt.eventId:
            candidate_id = _resolve_event_uuid(sess.id, pt.eventId)
            ev = db.get(EventModel, candidate_id) or db.scalar(
                select(EventModel).where(
                    EventModel.session_id == sess.id,
                    EventModel.organization_id == org_id,
                    EventModel.client_event_id == pt.eventId,
                )
            )
            if ev is not None and ev.organization_id == org_id:
                linked_ev_id = ev.id
                if ev.lat is None or ev.lng is None:
                    ev.lat = pt.lat
                    ev.lng = pt.lng

        db.add(
            LocationModel(
                organization_id=org_id,
                session_id=sess.id,
                vehicle_id=sess.vehicle_id or current_user.vehicle_id,
                driver_id=current_user.id,
                lat=pt.lat,
                lng=pt.lng,
                speed_kmh=pt.speedKmh,
                heading_deg=pt.headingDeg,
                ts=loc_ts,
                event_id=linked_ev_id,
            )
        )
        accepted += 1

    if accepted > 0:
        db.commit()
        live_state = build_live_driver_state(
            db, current_user, share_location=org_settings.share_location
        )
        sse_broker.publish(
            org_id,
            "driver_state",
            live_state.model_dump(mode="json"),
        )

    return LocationIngestResponse(accepted=accepted, shareLocationEnabled=True)


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

