from __future__ import annotations

from datetime import datetime, timezone
import math
from typing import Optional
from uuid import uuid4

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from ..models.models import (
    EventModel,
    LocationModel,
    OrgSettings,
    PushToken,
    RestBreak,
    RestStop,
    SessionModel,
    User,
    Vehicle,
)
from ..schemas.m3 import NearestRestStopItem, RestReminderPayload
from .mappers import (
    build_live_driver_state,
    ensure_utc,
    event_to_schema,
)
from .notify import notify_user
from .sse import sse_broker


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r_lat1 = math.radians(lat1)
    r_lng1 = math.radians(lng1)
    r_lat2 = math.radians(lat2)
    r_lng2 = math.radians(lng2)
    cos_val = math.cos(r_lat1) * math.cos(r_lat2) * math.cos(r_lng2 - r_lng1) + math.sin(
        r_lat1
    ) * math.sin(r_lat2)
    cos_val = max(-1.0, min(1.0, cos_val))
    return 6371.0 * math.acos(cos_val)


def find_nearest_rest_stops(
    db: Session,
    org_id: str,
    lat: float,
    lng: float,
    limit: int = 5,
) -> list[NearestRestStopItem]:
    """Return nearest rest stops ordered by ascending Haversine distance (`distanceKm`),
    scoped to shared stops (`organization_id IS NULL`) + organization's own stops.
    Uses `public.nearest_rest_stops()` directly on PostgreSQL and identical Haversine math on SQLite.
    """
    dialect = db.bind.dialect.name if db.bind is not None else "sqlite"
    if dialect == "postgresql":
        rows = db.execute(
            text(
                "SELECT id::text, name, stop_type, lat, lng, distance_km "
                "FROM public.nearest_rest_stops(:lat, :lng, :lim, CAST(:org AS uuid))"
            ),
            {"lat": float(lat), "lng": float(lng), "lim": int(limit), "org": org_id},
        ).all()
        stop_ids = [str(r[0]) for r in rows]
        extra_map = {
            s.id: s
            for s in db.scalars(select(RestStop).where(RestStop.id.in_(stop_ids))).all()
        }
        return [
            NearestRestStopItem(
                id=str(r[0]),
                name=str(r[1]),
                stopType=str(r[2]),
                lat=float(r[3]),
                lng=float(r[4]),
                distanceKm=round(float(r[5]), 2),
                open24h=extra_map[str(r[0])].open_24h if str(r[0]) in extra_map else False,
                hasTruckParking=extra_map[str(r[0])].has_truck_parking
                if str(r[0]) in extra_map
                else True,
            )
            for r in rows
        ]

    stops = db.scalars(
        select(RestStop).where(
            or_(RestStop.organization_id.is_(None), RestStop.organization_id == org_id)
        )
    ).all()
    scored = [
        (
            haversine_km(lat, lng, s.lat, s.lng),
            s,
        )
        for s in stops
    ]
    scored.sort(key=lambda item: item[0])
    return [
        NearestRestStopItem(
            id=s.id,
            name=s.name,
            stopType=s.stop_type,
            lat=s.lat,
            lng=s.lng,
            distanceKm=round(dist, 2),
            open24h=bool(s.open_24h),
            hasTruckParking=bool(s.has_truck_parking),
        )
        for dist, s in scored[: max(1, limit)]
    ]


def compute_effective_continuous_sec(
    db: Session,
    sess: SessionModel,
    org_settings: OrgSettings,
    reported_continuous_sec: Optional[int] = None,
    now_utc: Optional[datetime] = None,
) -> tuple[int, Optional[datetime]]:
    """Compute continuous driving seconds accounting for completed qualifying `rest_breaks`
    (`duration >= min_rest_min`). Returns `(continuous_sec, last_qualifying_rest_ended_at)`.
    """
    now = ensure_utc(now_utc) or datetime.now(timezone.utc)
    min_rest_sec = max(60, int(org_settings.min_rest_min) * 60)

    breaks = db.scalars(
        select(RestBreak)
        .where(
            RestBreak.organization_id == sess.organization_id,
            RestBreak.driver_id == sess.driver_id,
            RestBreak.session_id == sess.id,
        )
        .order_by(RestBreak.started_at.desc())
    ).all()

    last_valid_end: Optional[datetime] = None
    for rb in breaks:
        rb_start = ensure_utc(rb.started_at)
        rb_end = ensure_utc(rb.ended_at)
        if rb_start and rb_end and (rb_end - rb_start).total_seconds() >= min_rest_sec:
            last_valid_end = rb_end
            break

    if last_valid_end is not None:
        since_rest = max(0, int((now - last_valid_end).total_seconds()))
        return since_rest, last_valid_end

    if reported_continuous_sec is not None:
        return max(0, int(reported_continuous_sec)), None

    sess_start = ensure_utc(sess.started_at) or now
    elapsed = max(0, int((now - sess_start).total_seconds()))
    return max(int(sess.continuous_driving_sec or 0), elapsed), None


def evaluate_driving_hours_and_rest_reminder(
    db: Session,
    sess: SessionModel,
    driver: User,
    org_settings: OrgSettings,
    continuous_sec: int,
    last_rest_end: Optional[datetime],
    lat: Optional[float] = None,
    lng: Optional[float] = None,
    now_utc: Optional[datetime] = None,
) -> Optional[RestReminderPayload]:
    """Evaluate `continuous_sec` against `max_continuous_drive_min` and `rest_reminder_before_min`.
    When due, fetches nearest rest stops and idempotently notifies dispatchers via `LONG_DRIVING` event.
    """
    now = ensure_utc(now_utc) or datetime.now(timezone.utc)
    max_drive_min = max(1, int(org_settings.max_continuous_drive_min))
    remind_before_min = max(0, min(max_drive_min - 1, int(org_settings.rest_reminder_before_min)))

    remind_at_sec = (max_drive_min - remind_before_min) * 60
    max_limit_sec = max_drive_min * 60

    if continuous_sec < remind_at_sec:
        return None

    ref_lat = lat
    ref_lng = lng
    if ref_lat is None or ref_lng is None:
        latest_loc = db.scalar(
            select(LocationModel)
            .where(
                LocationModel.organization_id == driver.organization_id,
                LocationModel.driver_id == driver.id,
            )
            .order_by(LocationModel.ts.desc(), LocationModel.id.desc())
        )
        if latest_loc is not None:
            ref_lat = latest_loc.lat
            ref_lng = latest_loc.lng

    suggested: list[NearestRestStopItem] = []
    if ref_lat is not None and ref_lng is not None:
        suggested = find_nearest_rest_stops(
            db, driver.organization_id, ref_lat, ref_lng, limit=5
        )
    else:
        # Fallback to QL1A midpoint when driver has not enabled GPS so rest stop guidance is still available
        suggested = find_nearest_rest_stops(
            db, driver.organization_id, 19.8, 106.1, limit=3
        )

    over_limit = continuous_sec >= max_limit_sec
    epoch_tag = int(last_rest_end.timestamp()) if last_rest_end else 0
    client_ev_id = f"rest-drive-{sess.id}-{epoch_tag}"

    existing_ev = db.scalar(
        select(EventModel).where(
            EventModel.session_id == sess.id,
            EventModel.client_event_id == client_ev_id,
        )
    )
    target_lvl = 3 if over_limit else 2
    target_api_lvl = "CRITICAL" if over_limit else "WARNING"
    target_status = "ESCALATED" if over_limit else "OPEN"

    emit_alert = False
    if existing_ev is None:
        ev_id = str(uuid4())
        top_stop = suggested[0].name if suggested else "trạm dừng gần nhất"
        existing_ev = EventModel(
            id=ev_id,
            organization_id=driver.organization_id,
            session_id=sess.id,
            driver_id=driver.id,
            vehicle_id=sess.vehicle_id or driver.vehicle_id,
            client_event_id=client_ev_id,
            type="LONG_DRIVING",
            level=target_lvl,
            status=target_status,
            delayed=False,
            occurred_at=now,
            escalated_at=now if over_limit else None,
            lat=ref_lat,
            lng=ref_lng,
            note=f"Cần nghỉ tối thiểu {org_settings.min_rest_min} phút; gợi ý: {top_stop}",
            created_at=now,
            metrics={
                "api_level": target_api_lvl,
                "alert_action": "notify_dispatcher",
                "state": sess.current_state,
                "duration_sec": continuous_sec,
                "captured_at": now.isoformat(),
                "suggested_stop_id": suggested[0].id if suggested else None,
            },
        )
        db.add(existing_ev)
        if over_limit:
            sess.critical_count += 1
        else:
            sess.warning_count += 1
        db.flush()
        emit_alert = True
    elif target_lvl > existing_ev.level:
        existing_ev.level = target_lvl
        existing_ev.status = "ESCALATED"
        existing_ev.escalated_at = existing_ev.escalated_at or now
        m = dict(existing_ev.metrics or {})
        m["api_level"] = "CRITICAL"
        m["duration_sec"] = continuous_sec
        existing_ev.metrics = m
        sess.warning_count = max(0, sess.warning_count - 1)
        sess.critical_count += 1
        db.flush()
        emit_alert = True

    if emit_alert and existing_ev is not None:
        v_name = "Chưa phân xe"
        v_id = sess.vehicle_id or driver.vehicle_id
        if v_id:
            v_obj = db.get(Vehicle, v_id)
            if v_obj:
                v_name = v_obj.name
        alert_schema = event_to_schema(existing_ev, driver.full_name, v_name)
        sse_broker.publish(
            driver.organization_id,
            "alert",
            alert_schema.model_dump(mode="json"),
        )
        live_state = build_live_driver_state(
            db, driver, share_location=org_settings.share_location
        )
        sse_broker.publish(
            driver.organization_id,
            "driver_state",
            live_state.model_dump(mode="json"),
        )
        # Push reminder to driver's Android/Web device even if app is backgrounded (P3-7)
        has_drv_push = db.scalar(
            select(PushToken.id).where(
                PushToken.organization_id == driver.organization_id,
                PushToken.user_id == driver.id,
            )
        )
        if has_drv_push is not None:
            top_stop_name = suggested[0].name if suggested else "trạm dừng gần nhất"
            notify_user(
                db=db,
                recipient=driver,
                channel="push",
                title="Nhắc dừng nghỉ lái xe liên tục",
                body=f"Vui lòng nghỉ tối thiểu {org_settings.min_rest_min} phút tại {top_stop_name}",
                meta={"sessionId": sess.id, "eventId": existing_ev.id},
            )

    remaining_min = max(0, math.ceil((max_limit_sec - continuous_sec) / 60.0))
    return RestReminderPayload(
        shouldRest=True,
        overMaxLimit=over_limit,
        continuousDrivingMin=round(continuous_sec / 60.0, 1),
        maxContinuousDriveMin=max_drive_min,
        minRestMin=int(org_settings.min_rest_min),
        remainingMin=remaining_min,
        suggestedStops=suggested,
    )
