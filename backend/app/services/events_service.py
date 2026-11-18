from datetime import datetime, timezone
from uuid import NAMESPACE_DNS, UUID, uuid5

from fastapi import status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..core.errors import AppError
from ..models.models import (
    AppUsageDaily,
    Consent,
    EventModel,
    LocationModel,
    OrgSettings,
    PushToken,
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
    to_vn_time,
)
from .notify import notify_user
from .sse import sse_broker
from .webhook_service import dispatch_webhooks_for_event

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


def get_or_create_daily_usage(
    db: Session, org_id: str, driver_id: str, ref_utc: datetime
) -> AppUsageDaily:
    usage_day = to_vn_time(ref_utc).date()
    row = db.scalar(
        select(AppUsageDaily).where(
            AppUsageDaily.organization_id == org_id,
            AppUsageDaily.driver_id == driver_id,
            AppUsageDaily.usage_date == usage_day,
        )
    )
    if row is None:
        row = AppUsageDaily(
            organization_id=org_id,
            driver_id=driver_id,
            usage_date=usage_day,
            monitored_minutes=0,
            monitoring_off_count=0,
            alerts_total=0,
            alerts_false=0,
        )
        db.add(row)
        db.flush()
    return row


def classify_alert_level_from_settings(duration_sec: float, org_settings: OrgSettings) -> int:
    if duration_sec >= float(org_settings.level3_sec):
        return 3
    if duration_sec >= float(org_settings.level2_sec):
        return 2
    if duration_sec >= float(org_settings.level1_sec):
        return 1
    return 0


def alert_action_for_level(level: int) -> str:
    if level >= 3:
        return "notify_dispatcher"
    if level == 2:
        return "cabin_bell"
    return "gentle_reminder"


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
        metrics["alert_action"] = alert_action_for_level(incoming_lvl_int)
        if old_lvl_int < 3 and incoming_lvl_int >= 3:
            session_obj.warning_count = max(0, session_obj.warning_count - 1)
            session_obj.critical_count += 1
    elif "alert_action" not in metrics:
        metrics["alert_action"] = alert_action_for_level(existing.level)

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

    is_new_event = False
    entered_escalated = False

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
        prev_status = existing.status
        ev, incoming_delayed = _merge_existing_event(existing, session_obj, payload, now)
        if prev_status != "ESCALATED" and ev.status == "ESCALATED":
            entered_escalated = True
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
                        "alert_action": alert_action_for_level(lvl_int),
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
                usage_row = get_or_create_daily_usage(
                    db, driver.organization_id, driver.id, started_utc
                )
                usage_row.alerts_total += 1
                db.flush()
                is_new_event = True
                if ev.status == "ESCALATED":
                    entered_escalated = True
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
            prev_status = existing.status
            ev, incoming_delayed = _merge_existing_event(existing, session_obj, payload, now)
            if prev_status != "ESCALATED" and ev.status == "ESCALATED":
                entered_escalated = True

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
        # Rule: delayed events only go into history, NEVER emit SSE `alert`.
        # Multi-level rule (P3-3): when explicit severityLevel < 3 (Level 1 gentle reminder / Level 2 cabin bell),
        # only Level 3 notifies dispatchers via SSE `alert`! Legacy clients (severityLevel is None) keep M3 behavior.
        should_notify_dispatcher = payload.severityLevel is None or ev.level >= 3
        if not incoming_delayed and not ev.delayed and should_notify_dispatcher:
            sse_broker.publish(
                driver.organization_id,
                "alert",
                alert_schema.model_dump(mode="json"),
            )
            # Send background FCM push to operators who have registered push_tokens (closed tab support - P3-7)
            if ev.level >= 3 and ev.status != "CLOSED":
                token_owner_ids = set(
                    db.scalars(
                        select(PushToken.user_id).where(
                            PushToken.organization_id == driver.organization_id
                        )
                    ).all()
                )
                if token_owner_ids:
                    operators = db.scalars(
                        select(User).where(
                            User.organization_id == driver.organization_id,
                            User.role.in_(("dispatcher", "manager")),
                            User.is_active.is_(True),
                            User.id.in_(token_owner_ids),
                        )
                    ).all()
                    for op in operators:
                        notify_user(
                            db=db,
                            recipient=op,
                            channel="push",
                            title=f"Cảnh báo khẩn: {driver.full_name}",
                            body=f"{ev.type} ({vehicle_name})",
                            meta={"eventId": ev.id, "driverId": driver.id},
                        )

            alert_payload = alert_schema.model_dump(mode="json")
            if is_new_event:
                dispatch_webhooks_for_event(
                    db, driver.organization_id, "alert.created", alert_payload
                )
            if entered_escalated:
                dispatch_webhooks_for_event(
                    db, driver.organization_id, "alert.escalated", alert_payload
                )

    return alert_schema, incoming_delayed
