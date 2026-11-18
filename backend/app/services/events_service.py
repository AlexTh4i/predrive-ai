from datetime import datetime, timezone
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.errors import AppError
from ..models.models import (
    Consent,
    EventModel,
    LocationModel,
    SessionModel,
    User,
    Vehicle,
    level_str_to_int,
)
from ..schemas.m3 import AlertEvent, UpsertEventRequest
from .mappers import (
    build_live_driver_state,
    ensure_utc,
    event_to_schema,
    get_or_create_org_settings,
)
from .sse import sse_broker

STATUS_RANK: dict[str, int] = {
    "OPEN": 1,
    "ESCALATED": 2,
    "CLOSED": 3,
}

STATE_SEVERITY: dict[str, int] = {
    "OFFLINE": 0,
    "NORMAL": 1,
    "MONITORING_UNAVAILABLE": 2,
    "DISTRACTED": 3,
    "DROWSINESS_SIGNS": 4,
    "CRITICAL": 5,
    "DISCONNECTED": 5,
}


def _resolve_event_uuid(session_id: str, raw_event_id: str) -> str:
    try:
        return str(UUID(str(raw_event_id)))
    except ValueError:
        return str(uuid5(NAMESPACE_DNS, f"{session_id}:{raw_event_id}"))


def _resolve_incoming_level(payload: UpsertEventRequest) -> int:
    if payload.severityLevel is not None:
        return max(1, min(3, int(payload.severityLevel)))
    return level_str_to_int(payload.level)


def _is_location_allowed(db: Session, driver: User) -> bool:
    org_settings = get_or_create_org_settings(db, driver.organization_id)
    if not org_settings.share_location:
        return False
    consent = db.scalar(
        select(Consent)
        .where(
            Consent.user_id == driver.id,
            Consent.organization_id == driver.organization_id,
            Consent.consent_type == "data_processing",
        )
        .order_by(Consent.accepted_at.desc())
    )
    return bool(consent is not None and consent.location_consent)


def _sync_event_location(
    db: Session,
    ev: EventModel,
    session_obj: SessionModel,
    driver: User,
    payload: UpsertEventRequest,
    captured_utc: datetime,
) -> None:
    if not _is_location_allowed(db, driver):
        return

    lat = payload.lat
    lng = payload.lng
    speed = payload.speedKmh
    heading = payload.headingDeg

    if lat is None or lng is None:
        recent_loc = db.scalar(
            select(LocationModel)
            .where(
                LocationModel.session_id == session_obj.id,
                LocationModel.organization_id == driver.organization_id,
            )
            .order_by(LocationModel.ts.desc(), LocationModel.id.desc())
        )
        if recent_loc is not None:
            lat = recent_loc.lat
            lng = recent_loc.lng
            if speed is None:
                speed = recent_loc.speed_kmh
            if heading is None:
                heading = recent_loc.heading_deg

    if lat is None or lng is None:
        return

    ev.lat = lat
    ev.lng = lng

    existing_pin = db.scalar(
        select(LocationModel).where(
            LocationModel.organization_id == driver.organization_id,
            LocationModel.event_id == ev.id,
        )
    )
    if existing_pin is not None:
        existing_pin.lat = lat
        existing_pin.lng = lng
        if speed is not None:
            existing_pin.speed_kmh = speed
        if heading is not None:
            existing_pin.heading_deg = heading
    else:
        db.add(
            LocationModel(
                organization_id=driver.organization_id,
                session_id=session_obj.id,
                vehicle_id=ev.vehicle_id or session_obj.vehicle_id or driver.vehicle_id,
                driver_id=driver.id,
                lat=lat,
                lng=lng,
                speed_kmh=speed,
                heading_deg=heading,
                ts=captured_utc,
                event_id=ev.id,
            )
        )


def _merge_existing_event(
    existing: EventModel,
    session_obj: SessionModel,
    payload: UpsertEventRequest,
    now_utc: datetime,
) -> tuple[EventModel, bool]:
    """Monotonically merge incoming event update into existing record.
    Returns (event_model, is_incoming_delayed).
    """
    captured_utc = ensure_utc(payload.capturedAt) or now_utc
    started_utc = ensure_utc(payload.startedAt) or captured_utc
    incoming_delayed = (now_utc - captured_utc).total_seconds() > 60.0

    incoming_lvl_int = _resolve_incoming_level(payload)
    old_lvl_int = existing.level
    metrics = dict(existing.metrics or {})

    if incoming_lvl_int > old_lvl_int:
        existing.level = incoming_lvl_int
        metrics["api_level"] = "CRITICAL" if incoming_lvl_int >= 3 else payload.level
        if old_lvl_int < 3 and incoming_lvl_int >= 3:
            session_obj.warning_count = max(0, session_obj.warning_count - 1)
            session_obj.critical_count += 1

    if STATUS_RANK.get(payload.status, 1) > STATUS_RANK.get(existing.status, 1):
        existing.status = payload.status
        if payload.status == "ESCALATED" and existing.escalated_at is None:
            existing.escalated_at = now_utc
        elif payload.status == "CLOSED" and existing.closed_at is None:
            existing.closed_at = captured_utc

    if STATE_SEVERITY.get(payload.state, 0) >= STATE_SEVERITY.get(existing.state, 0):
        metrics["state"] = payload.state

    metrics["duration_sec"] = max(int(metrics.get("duration_sec") or 0), payload.durationSec)

    existing_started = ensure_utc(existing.occurred_at) or started_utc
    if started_utc < existing_started:
        existing.occurred_at = started_utc

    existing_captured = ensure_utc(existing.captured_at) or captured_utc
    if captured_utc >= existing_captured:
        metrics["captured_at"] = captured_utc.isoformat()

    if payload.riskScore is not None:
        cur_risk = metrics.get("risk_score")
        if cur_risk is None:
            metrics["risk_score"] = payload.riskScore
        else:
            metrics["risk_score"] = max(float(cur_risk), payload.riskScore)

    existing.metrics = metrics

    # Preserve non-delayed flag if it was originally received in real time
    if existing.delayed and not incoming_delayed:
        existing.delayed = False

    return existing, incoming_delayed


def upsert_session_event(
    db: Session,
    session_obj: SessionModel,
    driver: User,
    payload: UpsertEventRequest,
    now_utc: datetime | None = None,
    publish_sse: bool = True,
) -> tuple[AlertEvent, bool]:
    """Idempotent & monotonic upsert of an event for a driver session.
    Returns (AlertEvent schema, incoming_delayed).
    """
    now = ensure_utc(now_utc) or datetime.now(timezone.utc)
    captured_utc = ensure_utc(payload.capturedAt) or now
    started_utc = ensure_utc(payload.startedAt) or captured_utc
    incoming_delayed = (now - captured_utc).total_seconds() > 60.0

    resolved_id = _resolve_event_uuid(session_obj.id, payload.eventId)

    existing = db.get(EventModel, resolved_id)
    if existing is None:
        existing = db.scalar(
            select(EventModel).where(
                EventModel.session_id == session_obj.id,
                EventModel.client_event_id == payload.eventId,
            )
        )

    if existing is not None:
        if (
            existing.session_id != session_obj.id
            or existing.organization_id != driver.organization_id
        ):
            raise AppError(
                status.HTTP_409_CONFLICT,
                "EVENT_CONFLICT",
                "eventId already belongs to a different session",
            )
        ev, incoming_delayed = _merge_existing_event(existing, session_obj, payload, now)
    else:
        lvl_int = _resolve_incoming_level(payload)
        try:
            with db.begin_nested():
                ev = EventModel(
                    id=resolved_id,
                    organization_id=driver.organization_id,
                    session_id=session_obj.id,
                    driver_id=driver.id,
                    vehicle_id=session_obj.vehicle_id or driver.vehicle_id,
                    client_event_id=payload.eventId,
                    type=payload.type,
                    level=lvl_int,
                    status=payload.status,
                    delayed=incoming_delayed,
                    occurred_at=started_utc,
                    escalated_at=now if payload.status == "ESCALATED" else None,
                    closed_at=captured_utc if payload.status == "CLOSED" else None,
                    created_at=now,
                    metrics={
                        "api_level": "CRITICAL" if lvl_int >= 3 else payload.level,
                        "state": payload.state,
                        "risk_score": payload.riskScore,
                        "duration_sec": payload.durationSec,
                        "captured_at": captured_utc.isoformat(),
                    },
                )
                db.add(ev)
                if lvl_int >= 3:
                    session_obj.critical_count += 1
                else:
                    session_obj.warning_count += 1
                db.flush()
        except IntegrityError:
            existing = db.get(EventModel, resolved_id) or db.scalar(
                select(EventModel).where(
                    EventModel.session_id == session_obj.id,
                    EventModel.client_event_id == payload.eventId,
                )
            )
            if existing is None or existing.session_id != session_obj.id:
                raise AppError(
                    status.HTTP_409_CONFLICT,
                    "EVENT_CONFLICT",
                    "Concurrent event conflict",
                )
            ev, incoming_delayed = _merge_existing_event(existing, session_obj, payload, now)

    _sync_event_location(db, ev, session_obj, driver, payload, captured_utc)

    # Update live session state if session is still open and event is recent
    if session_obj.ended_at is None and not incoming_delayed:
        if ev.status == "CLOSED":
            session_obj.current_state = "NORMAL"
        else:
            session_obj.current_state = ev.state
        if session_obj.last_heartbeat_at is None or captured_utc > ensure_utc(
            session_obj.last_heartbeat_at
        ):  # type: ignore[operator]
            session_obj.last_heartbeat_at = captured_utc

    db.commit()
    db.refresh(ev)
    db.refresh(session_obj)

    v_id = ev.vehicle_id or session_obj.vehicle_id or driver.vehicle_id
    vehicle_name = "Chưa phân xe"
    if v_id:
        v_obj = db.get(Vehicle, v_id)
        if v_obj:
            vehicle_name = v_obj.name

    ack_by_name = None
    if ev.ack_by:
        ack_user = db.get(User, ev.ack_by)
        ack_by_name = ack_user.full_name if ack_user else (ev.metrics or {}).get("ack_by_name")
    elif (ev.metrics or {}).get("ack_by_name"):
        ack_by_name = (ev.metrics or {}).get("ack_by_name")

    alert_schema = event_to_schema(ev, driver.full_name, vehicle_name, ack_by_name=ack_by_name)

    if publish_sse:
        live_state = build_live_driver_state(db, driver)
        sse_broker.publish(
            driver.organization_id,
            "driver_state",
            live_state.model_dump(mode="json"),
        )
        # Rule: delayed events only go into history, NEVER emit SSE `alert`
        if not incoming_delayed and not ev.delayed:
            sse_broker.publish(
                driver.organization_id,
                "alert",
                alert_schema.model_dump(mode="json"),
            )

    return alert_schema, incoming_delayed
