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
    settings = db.scalar(
        select(OrgSettings).where(OrgSettings.organization_id == org_id)
    )
    if settings is None:
        settings = OrgSettings(
            organization_id=org_id,
            continuous_warn_sec=7200,
            continuous_critical_sec=10800,
            rest_reset_min=15,
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
        restResetMin=settings.rest_reset_min,
        shareLocation=settings.share_location,
        heartbeatIntervalSec=settings.heartbeat_interval_sec,
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
        phone=driver.phone,
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
) -> AlertEvent:
    return AlertEvent(
        id=ev.id,
        sessionId=ev.session_id,
        driverId=ev.driver_id,
        driverName=driver_name,
        vehicleName=vehicle_name,
        type=ev.type,  # type: ignore[arg-type]
        level=ev.level,  # type: ignore[arg-type]
        status=ev.status,  # type: ignore[arg-type]
        state=ev.state,  # type: ignore[arg-type]
        riskScore=ev.risk_score,
        startedAt=ensure_utc(ev.started_at),  # type: ignore[arg-type]
        durationSec=ev.duration_sec,
        delayed=ev.delayed,
        capturedAt=ensure_utc(ev.captured_at),  # type: ignore[arg-type]
        receivedAt=ensure_utc(ev.received_at),  # type: ignore[arg-type]
        ackBy=ev.ack_by,
        ackAt=ensure_utc(ev.ack_at),
        note=ev.note,
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

    # Also find most recent ended session if needed for lastHeartbeatAt
    last_session = active_session or db.scalar(
        select(SessionModel)
        .where(
            SessionModel.driver_id == driver.id,
            SessionModel.organization_id == driver.organization_id,
        )
        .order_by(SessionModel.started_at.desc())
    )

    day_start_utc, day_end_utc = vn_day_bounds_utc()

    # Drowsiness events today in VN timezone
    drowsy_today = db.scalar(
        select(func.count(EventModel.id)).where(
            EventModel.driver_id == driver.id,
            EventModel.organization_id == driver.organization_id,
            EventModel.type == "DROWSINESS",
            EventModel.started_at >= day_start_utc,
            EventModel.started_at <= day_end_utc,
        )
    ) or 0

    # Total driving sec today (ended sessions today + active session progress)
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
            .order_by(LocationModel.captured_at.desc(), LocationModel.id.desc())
        )
        if latest_loc is not None:
            loc_point = LocationPoint(
                lat=latest_loc.lat,
                lng=latest_loc.lng,
                at=ensure_utc(latest_loc.captured_at),  # type: ignore[arg-type]
            )

    return LiveDriverState(
        driverId=driver.id,
        fullName=driver.full_name,
        phone=driver.phone,
        vehicleName=v_name,
        state=state,  # type: ignore[arg-type]
        sessionId=session_id,
        continuousDrivingSec=continuous_sec,
        totalDrivingSec=total_driving_sec,
        drowsyCountToday=int(drowsy_today),
        lastHeartbeatAt=last_hb,
        location=loc_point,
    )

