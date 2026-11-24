from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models.models import (
    EventModel,
    LocationModel,
    OrgSettings,
    SessionModel,
    User,
    Vehicle,
)
from ..schemas.m3 import (
    AlertEvent,
    DriverSchema,
    LiveDriverState,
    LocationPoint,
    SessionSchema,
    SettingsSchema,
)

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


def ensure_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def to_vn_time(dt: datetime) -> datetime:
    utc_dt = ensure_utc(dt)
    assert utc_dt is not None
    return utc_dt.astimezone(VN_TZ)


def vn_day_bounds_utc(ref_utc: datetime | None = None) -> tuple[datetime, datetime]:
    now_utc = ensure_utc(ref_utc) or datetime.now(timezone.utc)
    now_vn = now_utc.astimezone(VN_TZ)
    start_vn = now_vn.replace(hour=0, minute=0, second=0, microsecond=0)
    end_vn = now_vn.replace(hour=23, minute=59, second=59, microsecond=999999)
    return start_vn.astimezone(timezone.utc), end_vn.astimezone(timezone.utc)


def get_or_create_org_settings(db: Session, org_id: str) -> OrgSettings:
    settings = db.get(OrgSettings, org_id)
    if settings is None:
        settings = OrgSettings(
            organization_id=org_id,
            continuous_warn_sec=7200,
            continuous_critical_sec=10800,
            min_rest_min=15,
            share_location=False,
            heartbeat_interval_sec=30,
        )
        db.add(settings)
        db.commit()
        db.refresh(settings)
    return settings


def settings_to_schema(settings: OrgSettings) -> SettingsSchema:
    return SettingsSchema(
        continuousWarnSec=settings.continuous_warn_sec,
        continuousCriticalSec=settings.continuous_critical_sec,
        restResetMin=settings.min_rest_min,
        shareLocation=settings.share_location,
        heartbeatIntervalSec=settings.heartbeat_interval_sec,
        earThreshold=round(float(settings.ear_threshold), 4),
        eyeClosedSec=round(float(settings.eye_closed_sec), 2),
        headPoseSec=round(float(settings.head_pose_sec), 2),
        tooDarkThreshold=round(float(settings.too_dark_threshold), 2),
        level1Sec=round(float(settings.level1_sec), 2),
        level2Sec=round(float(settings.level2_sec), 2),
        level3Sec=round(float(settings.level3_sec), 2),
        ackTimeoutSec=settings.ack_timeout_sec,
        maxContinuousDriveMin=settings.max_continuous_drive_min,
        restReminderBeforeMin=settings.rest_reminder_before_min,
        locationIntervalSec=settings.location_interval_sec,
        heartbeatRetentionDays=settings.heartbeat_retention_days,
        locationRetentionDays=settings.location_retention_days,
        eventRetentionDays=settings.event_retention_days,
        auditRetentionDays=settings.audit_retention_days,
    )


def get_vehicle_name_map(db: Session, org_id: str) -> dict[str, str]:
    vehicles = db.scalars(
        select(Vehicle).where(Vehicle.organization_id == org_id)
    ).all()
    return {v.id: v.name for v in vehicles}


def driver_to_schema(
    driver: User, vehicle_map: dict[str, str]
) -> DriverSchema:
    v_name = (
        vehicle_map.get(driver.vehicle_id, "Chưa phân xe")
        if driver.vehicle_id
        else "Chưa phân xe"
    )
    return DriverSchema(
        id=driver.id,
        fullName=driver.full_name,
        phone=driver.phone or "",
        vehicleId=driver.vehicle_id,
        vehicleName=v_name,
        avatarUrl=driver.avatar_url,
    )


def session_to_schema(s: SessionModel) -> SessionSchema:
    return SessionSchema(
        id=s.id,
        driverId=s.driver_id,
        startedAt=ensure_utc(s.started_at),  # type: ignore[arg-type]
        endedAt=ensure_utc(s.ended_at),
        totalDrivingSec=s.total_driving_sec,
        warningCount=s.warning_count,
        criticalCount=s.critical_count,
    )


def event_to_schema(
    ev: EventModel,
    driver_name: str,
    vehicle_name: str,
    ack_by_name: str | None = None,
) -> AlertEvent:
    resolved_ack_by = ack_by_name
    if resolved_ack_by is None and ev.metrics:
        resolved_ack_by = ev.metrics.get("ack_by_name")
    alert_action = (ev.metrics or {}).get("alert_action")
    if not alert_action:
        if ev.level >= 3:
            alert_action = "notify_dispatcher"
        elif ev.level == 2:
            alert_action = "cabin_bell"
        else:
            alert_action = "gentle_reminder"
    return AlertEvent(
        id=ev.id,
        sessionId=ev.session_id,
        driverId=ev.driver_id,
        driverName=driver_name,
        vehicleName=vehicle_name,
        type=ev.type,  # type: ignore[arg-type]
        level=ev.level_str,  # type: ignore[arg-type]
        severityLevel=int(ev.level),
        alertAction=alert_action,
        status=ev.status,  # type: ignore[arg-type]
        state=ev.state,  # type: ignore[arg-type]
        riskScore=ev.risk_score,
        startedAt=ensure_utc(ev.occurred_at),  # type: ignore[arg-type]
        durationSec=ev.duration_sec,
        delayed=ev.delayed,
        capturedAt=ensure_utc(ev.captured_at),  # type: ignore[arg-type]
        receivedAt=ensure_utc(ev.created_at),  # type: ignore[arg-type]
        ackBy=resolved_ack_by,
        ackAt=ensure_utc(ev.ack_at),
        note=ev.note,
        lat=ev.lat,
        lng=ev.lng,
        driverFeedback=ev.driver_feedback,
    )


def build_live_driver_state(
    db: Session,
    driver: User,
    vehicle_map: dict[str, str] | None = None,
    share_location: bool | None = None,
) -> LiveDriverState:
    if vehicle_map is None:
        vehicle_map = get_vehicle_name_map(db, driver.organization_id)
    if share_location is None:
        org_settings = get_or_create_org_settings(db, driver.organization_id)
        share_location = org_settings.share_location

    active_session = db.scalar(
        select(SessionModel)
        .where(
            SessionModel.driver_id == driver.id,
            SessionModel.organization_id == driver.organization_id,
            SessionModel.ended_at.is_(None),
        )
        .order_by(SessionModel.started_at.desc())
    )

    last_session = active_session or db.scalar(
        select(SessionModel)
        .where(
            SessionModel.driver_id == driver.id,
            SessionModel.organization_id == driver.organization_id,
        )
        .order_by(SessionModel.started_at.desc())
    )

    day_start_utc, day_end_utc = vn_day_bounds_utc()

    drowsy_today = db.scalar(
        select(func.count(EventModel.id)).where(
            EventModel.driver_id == driver.id,
            EventModel.organization_id == driver.organization_id,
            EventModel.type.in_(("DROWSINESS", "DROWSY", "HEAD_DOWN")),
            EventModel.occurred_at >= day_start_utc,
            EventModel.occurred_at <= day_end_utc,
        )
    ) or 0

    ended_today_sec = db.scalar(
        select(func.coalesce(func.sum(SessionModel.total_driving_sec), 0)).where(
            SessionModel.driver_id == driver.id,
            SessionModel.organization_id == driver.organization_id,
            SessionModel.started_at >= day_start_utc,
            SessionModel.started_at <= day_end_utc,
            SessionModel.ended_at.is_not(None),
        )
    ) or 0

    if active_session is not None:
        state = active_session.current_state
        session_id = active_session.id
        continuous_sec = active_session.continuous_driving_sec
        active_sec = max(active_session.total_driving_sec, continuous_sec)
        total_driving_sec = int(ended_today_sec) + int(active_sec)
        last_hb = ensure_utc(active_session.last_heartbeat_at)
        v_id = active_session.vehicle_id or driver.vehicle_id
    else:
        state = "OFFLINE"
        session_id = None
        continuous_sec = 0
        total_driving_sec = int(ended_today_sec)
        last_hb = ensure_utc(last_session.last_heartbeat_at) if last_session else None
        v_id = driver.vehicle_id

    v_name = vehicle_map.get(v_id, "Chưa phân xe") if v_id else "Chưa phân xe"

    loc_point: LocationPoint | None = None
    if share_location:
        latest_loc = db.scalar(
            select(LocationModel)
            .where(
                LocationModel.driver_id == driver.id,
                LocationModel.organization_id == driver.organization_id,
            )
            .order_by(LocationModel.ts.desc(), LocationModel.id.desc())
        )
        if latest_loc is not None:
            loc_point = LocationPoint(
                lat=latest_loc.lat,
                lng=latest_loc.lng,
                at=ensure_utc(latest_loc.ts),  # type: ignore[arg-type]
                speedKmh=latest_loc.speed_kmh,
                headingDeg=latest_loc.heading_deg,
                eventId=latest_loc.event_id,
            )

    return LiveDriverState(
        driverId=driver.id,
        fullName=driver.full_name,
        phone=driver.phone or "",
        vehicleName=v_name,
        state=state,  # type: ignore[arg-type]
        sessionId=session_id,
        continuousDrivingSec=continuous_sec,
        totalDrivingSec=total_driving_sec,
        drowsyCountToday=int(drowsy_today),
        lastHeartbeatAt=last_hb,
        location=loc_point,
    )
