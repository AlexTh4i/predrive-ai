from datetime import datetime, timezone
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.errors import AppError
from ..models.models import (
    EventModel,
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

    incoming_lvl_int = level_str_to_int(payload.level)
    old_lvl_int = existing.level
    metrics = dict(existing.metrics or {})

    if incoming_lvl_int > old_lvl_int:
        existing.level = incoming_lvl_int
        metrics["api_level"] = payload.level
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
        lvl_int = level_str_to_int(payload.level)
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
                        "api_level": payload.level,
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
